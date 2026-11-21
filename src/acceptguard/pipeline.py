"""Run the whole flow over a ledger: scope gate, extract, verify, decide."""
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from acceptguard.clock import Period, ledger_baseline
from acceptguard.decide import InvoiceOutcome, decide, scope_gate
from acceptguard.extract import ExtractionError, extract
from acceptguard.ingest import LedgerRow, SourceText, evidence_files, load_ledger, source_text
from acceptguard.models import Abstention, DocExtraction
from acceptguard.verify import VerifiedDoc, verify_document

Extractor = Callable[[Path], DocExtraction]
SourceReader = Callable[[Path], SourceText]


@dataclass(frozen=True)
class DocRun:
    """What one file contributed: the model's extraction and the verification of each field."""

    path: Path
    extraction: DocExtraction | None
    verified: VerifiedDoc | None = None
    error: str | None = None


@dataclass(frozen=True)
class InvoiceRun:
    row: LedgerRow
    outcome: InvoiceOutcome
    files: tuple[Path, ...]
    docs: tuple[DocRun, ...] = ()


def default_extractor(path: Path) -> DocExtraction:
    return extract(path).extraction


def run(
    ledger_path: Path,
    evidence_dir: Path,
    period: Period,
    *,
    extractor: Extractor = default_extractor,
    reader: SourceReader = source_text,
) -> list[InvoiceRun]:
    return [_run_one(row, evidence_dir, period, extractor, reader) for row in load_ledger(ledger_path)]


def run_invoice(row: LedgerRow, evidence_dir: Path, period: Period, *, extractor: Extractor = default_extractor,
                reader: SourceReader = source_text) -> InvoiceRun:
    """One ledger row; the web app uses this so it shares the exact evaluated code path."""
    return _run_one(row, evidence_dir, period, extractor, reader)


def _run_one(row: LedgerRow, evidence_dir: Path, period: Period, extractor: Extractor, reader: SourceReader) -> InvoiceRun:
    files = tuple(evidence_files(evidence_dir, row.invoice_no))
    if scope_gate(row):  # out-of-scope rows cost no model calls
        return InvoiceRun(row, decide(row, [], period), files)
    docs: list[DocRun] = []
    for path in files:
        try:
            extraction = extractor(path)
        except ExtractionError as error:
            docs.append(DocRun(path, None, error=str(error)))
            return InvoiceRun(row, _extraction_failed(row, period, error), files, tuple(docs))
        if not has_facts(extraction):
            docs.append(DocRun(path, extraction))
            return InvoiceRun(row, _abstain(row, period, Abstention(
                "NO_FACTS_EXTRACTED", f"{path.name}: no date or payment term was extracted; a person must read it")), files, tuple(docs))
        docs.append(DocRun(path, extraction, verify_document(extraction, reader(path), row.invoice_no)))
    return InvoiceRun(row, decide(row, [doc.verified for doc in docs], period), files, tuple(docs))


def has_facts(extraction: DocExtraction) -> bool:
    """A dropped fact cannot be caught by verification, so every uploaded file must contribute one."""
    cited = (extraction.delivery, extraction.objection_raised, extraction.objection_recorded, extraction.objection_removed)
    return any(c.date_text or c.iso_date or c.quote for c in cited) or extraction.credit_days is not None


def _abstain(row: LedgerRow, period: Period, reason: Abstention) -> InvoiceOutcome:
    ledger = ledger_baseline(row.invoice_date, row.credit_days, row.payment_date, period).decision
    return InvoiceOutcome(row.invoice_no, "ABSTAIN", None, ledger, (reason,))


def _extraction_failed(row: LedgerRow, period: Period, error: ExtractionError) -> InvoiceOutcome:
    return _abstain(row, period, Abstention("EXTRACTION_FAILED", str(error)))
