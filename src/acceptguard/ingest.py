"""Read the ledger CSV and turn each evidence file into checkable source text."""
import csv
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from email import policy
from email.parser import BytesParser
from io import BytesIO
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ValidationError, field_validator
from pypdf import PdfReader

from acceptguard.dates import email_sent_date
from acceptguard.models import Abstention

EVIDENCE_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg", ".txt", ".eml"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg"}
OCR_TIMEOUT_S = 30
MAX_OCR_PIXELS = 40_000_000

Ocr = Callable[[bytes], str | None]


class LedgerError(ValueError):
    pass


class LedgerRow(BaseModel):
    """Ledger dates must be ISO (YYYY-MM-DD) so the ledger itself is never ambiguous."""

    invoice_no: str
    vendor: str
    vendor_category: str
    invoice_date: date
    amount: Decimal
    credit_days: int | None = None
    paid_amount: Decimal | None = None
    payment_date: date | None = None

    @field_validator("credit_days", "paid_amount", "payment_date", mode="before")
    @classmethod
    def blank_is_none(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("vendor_category", mode="before")
    @classmethod
    def lowercase_category(cls, value: object) -> object:
        return value.strip().casefold() if isinstance(value, str) else value


def load_ledger(path: Path) -> list[LedgerRow]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    ledger = []
    for line_number, raw in enumerate(rows, start=2):  # line 1 is the header
        try:
            ledger.append(LedgerRow.model_validate(raw))
        except ValidationError as error:
            raise LedgerError(f"{path.name} row {line_number}: {error}") from error
    return ledger


def evidence_files(evidence_dir: Path, invoice_no: str) -> list[Path]:
    folder = evidence_dir / invoice_no
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.iterdir() if p.suffix.lower() in EVIDENCE_SUFFIXES)


@dataclass(frozen=True)
class SourceText:
    kind: Literal["text", "image", "email"]
    text: str | None  # None only when an image needed OCR and OCR was unavailable
    email_date: date | Abstention | None = None


def tesseract_ocr(image: bytes) -> str | None:
    """OCR with the local Tesseract binary; None if it is not installed."""
    if shutil.which("tesseract") is None:
        return None
    import pytesseract
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = MAX_OCR_PIXELS  # larger images raise instead of being decoded
    try:
        return pytesseract.image_to_string(Image.open(BytesIO(image)), timeout=OCR_TIMEOUT_S)
    except (RuntimeError, Image.DecompressionBombError, OSError):
        return None  # OCR could not run: dates from this image stay unverified, so the invoice abstains


def source_text(path: Path, ocr: Ocr = tesseract_ocr) -> SourceText:
    suffix = path.suffix.lower()
    data = path.read_bytes()
    if suffix == ".eml":
        return _email_source(data)
    if suffix == ".txt":
        return SourceText("text", data.decode("utf-8", errors="replace"))
    if suffix in IMAGE_SUFFIXES:
        return SourceText("image", ocr(data))
    if suffix == ".pdf":
        return _pdf_source(data, ocr)
    raise ValueError(f"unsupported evidence type: {path.name}")


EMAIL_VIEW_HEADERS = ("From", "To", "Subject", "Date")


def email_view(data: bytes) -> str:
    """Decoded headers plus plain-text body: exactly what the model sees and what quotes are checked against."""
    message = BytesParser(policy=policy.default).parsebytes(data)
    headers = [f"{name}: {message[name]}" for name in EMAIL_VIEW_HEADERS if message[name] is not None]
    body = message.get_body(preferencelist=("plain",))
    return "\n".join(headers) + "\n\n" + (body.get_content() if body is not None else "")


def _email_source(data: bytes) -> SourceText:
    return SourceText("email", email_view(data), email_sent_date(data))


def _pdf_source(data: bytes, ocr: Ocr) -> SourceText:
    """Text-layer PDFs are checked exactly; scanned PDFs are OCR'd from their embedded page images."""
    reader = PdfReader(BytesIO(data))
    text = "\n".join(page.extract_text() or "" for page in reader.pages).strip()
    if text:
        return SourceText("text", text)
    pieces = [ocr(image.data) for page in reader.pages for image in page.images]
    if not pieces or any(piece is None for piece in pieces):
        return SourceText("image", None)
    return SourceText("image", "\n".join(pieces))
