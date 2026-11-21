"""Shared result type and the extraction schema sent to Gemini.

The schema reports what a document says. It never carries legal judgments:
no is_written, no acceptance_date, no confidence.
"""
from dataclasses import dataclass
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


@dataclass(frozen=True)
class Abstention:
    """Route to the CA instead of computing. `code` is a stable reason code."""

    code: str
    detail: str = ""


class Cited(BaseModel):
    date_text: str | None = Field(None, description="The date exactly as written in the document.")
    iso_date: date | None = Field(None, description="The same date as YYYY-MM-DD.")
    quote: str | None = Field(None, description="The exact sentence or line containing date_text.")


class DocExtraction(BaseModel):
    doc_type: Literal["challan", "email", "contract", "other"]
    invoice_ref: str | None = Field(None, description="Invoice number this document refers to, exactly as written.")
    delivery: Cited = Field(description="Date the buyer received the goods or service (receipt stamp or signature).")
    objection_raised: Cited = Field(description="Date the buyer first complained about the goods, in any medium.")
    objection_recorded: Cited = Field(description="Date of the written complaint record in this document.")
    objection_medium: Literal["email", "letter", "whatsapp", "phone", "in_person"] | None = None
    objection_location: Literal["top_message", "quoted_text", "attachment"] | None = None
    objection_removed: Cited = Field(description="Date the supplier fixed, replaced or resolved the complaint.")
    credit_days: int | None = Field(None, description="Agreed payment period in days.")
    credit_basis: Literal["invoice", "delivery", "acceptance", "unspecified"] | None = None
    credit_quote: str | None = Field(None, description="The exact sentence stating the payment period.")
    illegible_regions: list[str] = Field(default_factory=list, description="Parts of the document that cannot be read.")
