"""Run the whole flow over a ledger: scope gate, extract, verify, decide."""
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from acceptguard.clock import Period, ledger_baseline
from acceptguard.decide import InvoiceOutcome, decide, scope_gate
from acceptguard.extract import ExtractionError, extract
from acceptguard.ingest import LedgerRow, SourceText, evidence_files, load_ledger, source_text
from acceptguard.models import Abstention, DocExtraction
from acceptguard.verify import verify_document

Extractor = Callable[[Path], DocExtraction]
SourceReader = Callable[[Path], SourceText]


@dataclass(frozen=True)
class InvoiceRun:
    row: LedgerRow
    outcome: InvoiceOutcome
    files: tuple[Path, ...]


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


def _run_one(row: LedgerRow, evidence_dir: Path, period: Period, extractor: Extractor, reader: SourceReader) -> InvoiceRun:
    files = tuple(evidence_files(evidence_dir, row.invoice_no))
    if scope_gate(row):  # out-of-scope rows cost no model calls
        return InvoiceRun(row, decide(row, [], period), files)
    verified = []
    for path in files:
        try:
            extraction = extractor(path)
        except ExtractionError as error:
            return InvoiceRun(row, _extraction_failed(row, period, error), files)
        verified.append(verify_document(extraction, reader(path), row.invoice_no))
    return InvoiceRun(row, decide(row, verified, period), files)


def _extraction_failed(row: LedgerRow, period: Period, error: ExtractionError) -> InvoiceOutcome:
    ledger = ledger_baseline(row.invoice_date, row.credit_days, row.payment_date, period).decision
    return InvoiceOutcome(row.invoice_no, "ABSTAIN", None, ledger, (Abstention("EXTRACTION_FAILED", str(error)),))
