"""End-to-end over the synthetic dev set with perfect extractions (the ground truth stands in for Gemini).

This checks ingest -> verify -> decide -> clock against hand-written labels without an API key.
It says nothing about model accuracy; that is what eval/score.py measures.
"""
from decimal import Decimal
from pathlib import Path

import pytest

from acceptguard.cli import main
from acceptguard.decide import scope_gate
from acceptguard.ingest import LedgerRow, SourceText, source_text
from acceptguard.models import DocExtraction
from acceptguard.pipeline import run
from acceptguard.report import inr, write_csv, write_html
from acceptguard.synthetic.__main__ import write_dataset
from acceptguard.synthetic.scenarios import PERIOD, SCENARIOS


DOCS = {(s.invoice_no, doc.filename): doc for s in SCENARIOS for doc in s.docs}


def perfect_extractor(path: Path) -> DocExtraction:
    return DOCS[(path.parent.name, path.name)].expected


def simulated_reader(path: Path) -> SourceText:
    doc = DOCS[(path.parent.name, path.name)]
    ocr_text = doc.simulated_ocr if doc.simulated_ocr is not None else doc.text
    return source_text(path, ocr=lambda _image: ocr_text)


@pytest.fixture(scope="module")
def dataset(tmp_path_factory):
    out = tmp_path_factory.mktemp("dev")
    write_dataset(out)
    return out


@pytest.fixture(scope="module")
def runs(dataset):
    found = run(dataset / "ledger.csv", dataset / "evidence", PERIOD, extractor=perfect_extractor, reader=simulated_reader)
    return {r.outcome.invoice_no: r for r in found}


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: f"{s.invoice_no} {s.title}")
def test_scenario_with_perfect_extraction(runs, scenario):
    outcome = runs[scenario.invoice_no].outcome
    reason = outcome.reasons[0].code if outcome.reasons else None
    assert (outcome.status, outcome.decision, reason) == (
        scenario.expected_status,
        scenario.expected_decision,
        scenario.expected_reason,
    ), outcome.reasons
    assert outcome.ledger_decision == scenario.expected_ledger_decision


def row(**overrides) -> LedgerRow:
    base = {"invoice_no": "INV-X", "vendor": "v", "vendor_category": "micro", "invoice_date": "2026-03-01",
            "amount": "100", "paid_amount": "100", "payment_date": "2026-03-10"}
    return LedgerRow.model_validate(base | overrides)


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        pytest.param({"vendor_category": "trader"}, "CATEGORY_UNCLEAR", id="trader routed to CA"),
        pytest.param({"vendor_category": ""}, "CATEGORY_UNCLEAR", id="blank category"),
        pytest.param({"paid_amount": ""}, "LEDGER_INCOMPLETE", id="payment date without amount"),
        pytest.param({"paid_amount": "150"}, "LEDGER_INCOMPLETE", id="overpaid"),
        pytest.param({"paid_amount": "40"}, "OUT_OF_SCOPE_PARTIAL", id="part-paid"),
    ],
)
def test_scope_gate(overrides, code):
    assert scope_gate(row(**overrides)).code == code


def test_scope_gate_passes_full_payment():
    assert scope_gate(row()) is None
    assert row().paid_amount == Decimal("100")


def test_out_of_scope_rows_make_no_model_calls(dataset):
    calls = []

    def counting_extractor(path):
        calls.append(path.parent.name)
        return perfect_extractor(path)

    run(dataset / "ledger.csv", dataset / "evidence", PERIOD, extractor=counting_extractor, reader=simulated_reader)
    assert "INV-016" not in calls and "INV-017" not in calls


def test_report_escapes_evidence_and_counts(runs, tmp_path):
    first = next(iter(runs.values()))
    hostile = first.outcome.__class__(**{**first.outcome.__dict__, "notes": ("<script>alert(1)</script>",)})
    items = [first.__class__(first.row, hostile, first.files), *list(runs.values())[1:]]
    write_html(items, tmp_path / "report.html", PERIOD, "gemini-3.5-flash-lite")
    html = (tmp_path / "report.html").read_text()
    assert "<script>alert" not in html and "&lt;script&gt;" in html
    assert html.count("<details>") == len(SCENARIOS)
    assert "Candidates for review only" in html
    write_csv(items, tmp_path / "report.csv")
    assert (tmp_path / "report.csv").read_text().count("\n") == len(SCENARIOS) + 1


def test_cli_without_api_key_routes_everything_to_ca(dataset, tmp_path, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)  # empty extraction cache
    out = tmp_path / "out"
    code = main([str(dataset / "ledger.csv"), str(dataset / "evidence"), "--fy-end", "2026-03-31",
                 "--as-of", "2026-10-01", "--out", str(out)])
    csv_text = (out / "report.csv").read_text()
    assert code == 0
    assert csv_text.count("EXTRACTION_FAILED") == len(SCENARIOS) - 2  # two rows are out of scope


@pytest.mark.parametrize(("amount", "text"), [("118000.00", "₹1,18,000.00"), ("950", "₹950.00"), ("12345678.5", "₹1,23,45,678.50")])
def test_indian_digit_grouping(amount, text):
    assert inr(Decimal(amount)) == text


def test_late_written_objection_is_explained(runs):
    notes = " ".join(runs["INV-005"].outcome.notes)
    assert "2026-03-28 is after the objection window closed on 2026-03-25" in notes
    assert "Complaint first raised 2026-03-20" in notes
