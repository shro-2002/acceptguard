"""Synthetic evidence documents. Each builder returns the text it renders and the ground-truth extraction.

Ground truth comes from the builder arguments, never from the model or the clock.
"""
from dataclasses import dataclass
from datetime import date, datetime, time
from email.message import EmailMessage
from email.utils import format_datetime
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from acceptguard.models import Cited, DocExtraction

IST = ZoneInfo("Asia/Kolkata")
BUYER = "Kaveri Auto Components Pvt Ltd"
SUPPLIER = "Sharma Precision Castings"
EMAIL_SENT_AT = time(10, 30)
LINE_HEIGHT = 40
MARGIN = 40
FONT_SIZE = 22

DateStyle = Literal["long", "numeric"]


@dataclass(frozen=True)
class SynthDoc:
    filename: str
    kind: Literal["image", "pdf", "email"]
    lines: tuple[str, ...]
    expected: DocExtraction
    email_sent: date | None = None
    blur: float = 0.0
    simulated_ocr: str | None = None  # what OCR returns in tests; None means the rendered text

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


def fmt(day: date, style: DateStyle = "long") -> str:
    return f"{day.day} {day:%B} {day.year}" if style == "long" else f"{day:%d/%m/%Y}"


def cite(day: date, quote: str, style: DateStyle = "long") -> Cited:
    return Cited(date_text=fmt(day, style), iso_date=day, quote=quote)


def _extraction(doc_type: str, **fields: object) -> DocExtraction:
    empty = {"delivery": Cited(), "objection_raised": Cited(), "objection_recorded": Cited(), "objection_removed": Cited()}
    return DocExtraction.model_validate({"doc_type": doc_type, **empty, **fields})


def challan(invoice_ref: str, received: date, *, dispatch: date | None = None, style: DateStyle = "long",
            blur: float = 0.0, simulated_ocr: str | None = None) -> SynthDoc:
    stamp = f"RECEIVED {fmt(received, style)} - Stores, {BUYER}"
    lines = [f"DELIVERY CHALLAN  Supplier: {SUPPLIER}", f"Invoice No: {invoice_ref}"]
    if dispatch is not None:
        lines.append(f"Dispatch date: {fmt(dispatch, style)}")
    lines += ["Goods: 400 x aluminium housings, batch 7", stamp]
    expected = _extraction("challan", invoice_ref=invoice_ref, delivery=cite(received, stamp, style))
    return SynthDoc("challan.png", "image", tuple(lines), expected, blur=blur, simulated_ocr=simulated_ocr)


def objection_email(invoice_ref: str, sent: date, *, phone_on: date | None = None) -> SynthDoc:
    rejection = "Please treat this email as our formal rejection." if phone_on else "We reject the consignment until it is replaced."
    first = (f"Invoice {invoice_ref}: as discussed on the phone on {fmt(phone_on, 'numeric')}, batch 7 is defective."
             if phone_on else f"Invoice {invoice_ref}: batch 7 has cracked housings.")
    raised = cite(phone_on, first, "numeric") if phone_on else Cited()
    expected = _extraction(
        "email",
        invoice_ref=invoice_ref,
        objection_raised=raised,
        objection_recorded=Cited(iso_date=sent, quote=rejection),
        objection_medium="email",
        objection_location="top_message",
    )
    return SynthDoc("objection.eml", "email", (first, rejection), expected, email_sent=sent)


def removal_email(invoice_ref: str, sent: date, replaced_on: date) -> SynthDoc:
    line = f"Replacement units for invoice {invoice_ref} were delivered and accepted on {fmt(replaced_on)}."
    expected = _extraction("email", invoice_ref=invoice_ref, objection_removed=cite(replaced_on, line))
    return SynthDoc("removal.eml", "email", (line,), expected, email_sent=sent)


def delivery_email(invoice_ref: str, sent: date, received: date) -> SynthDoc:
    line = f"We received the goods for invoice {invoice_ref} on {fmt(received)}."
    expected = _extraction("email", invoice_ref=invoice_ref, delivery=cite(received, line))
    return SynthDoc("delivery.eml", "email", (line,), expected, email_sent=sent)


def contract(days: int, basis: Literal["invoice", "delivery", "acceptance"]) -> SynthDoc:
    phrase = {"invoice": "the invoice date", "delivery": "delivery of the goods", "acceptance": "acceptance of the goods"}[basis]
    clause = f"Clause 7. Payment shall be made within {days} days of {phrase}."
    expected = _extraction("contract", credit_days=days, credit_basis=basis, credit_quote=clause)
    return SynthDoc("contract.pdf", "pdf", (f"MASTER SUPPLY AGREEMENT - {BUYER} and {SUPPLIER}", clause), expected)


def render(doc: SynthDoc, folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / doc.filename
    if doc.kind == "email":
        path.write_bytes(_email_bytes(doc))
        return path
    image = _draw(doc.lines, doc.blur)
    image.save(path, "PDF", resolution=150) if doc.kind == "pdf" else image.save(path, "PNG")
    return path


def _email_bytes(doc: SynthDoc) -> bytes:
    message = EmailMessage()
    message["From"] = "accounts@example.in"
    message["To"] = "stores@example.in"
    message["Subject"] = f"Re: {doc.expected.invoice_ref or 'supply'}"
    message["Date"] = format_datetime(datetime.combine(doc.email_sent, EMAIL_SENT_AT, IST))
    message.set_content(doc.text)
    return message.as_bytes()


def _draw(lines: tuple[str, ...], blur: float) -> Image.Image:
    font = ImageFont.load_default(size=FONT_SIZE)
    image = Image.new("RGB", (1100, MARGIN * 2 + LINE_HEIGHT * len(lines)), "white")
    pen = ImageDraw.Draw(image)
    for index, line in enumerate(lines):
        pen.text((MARGIN, MARGIN + index * LINE_HEIGHT), line, fill="black", font=font)
    return image.filter(ImageFilter.GaussianBlur(blur)) if blur else image
