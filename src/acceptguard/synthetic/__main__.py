"""Write the synthetic dev set: python -m acceptguard.synthetic eval/data/dev"""
import csv
import json
import sys
from pathlib import Path

from acceptguard.synthetic.documents import render
from acceptguard.synthetic.scenarios import PERIOD, SCENARIOS, Scenario


def write_dataset(out_dir: Path, scenarios: tuple[Scenario, ...] = SCENARIOS) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = [s.ledger_row() for s in scenarios]
    with (out_dir / "ledger.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    labels = {"fy_end": PERIOD.fy_end.isoformat(), "as_of": PERIOD.as_of.isoformat(), "invoices": []}
    for scenario in scenarios:
        folder = out_dir / "evidence" / scenario.invoice_no
        for doc in scenario.docs:
            render(doc, folder)
        labels["invoices"].append(_label(scenario))
    (out_dir / "labels.json").write_text(json.dumps(labels, indent=2), encoding="utf-8")


def _label(scenario: Scenario) -> dict:
    return {
        "invoice_no": scenario.invoice_no,
        "title": scenario.title,
        "expected_status": scenario.expected_status,
        "expected_decision": scenario.expected_decision,
        "expected_reason": scenario.expected_reason,
        "expected_ledger_decision": scenario.expected_ledger_decision,
        "docs": [
            {"file": doc.filename, "text": doc.text, "expected": doc.expected.model_dump(mode="json"), "simulated_ocr": doc.simulated_ocr}
            for doc in scenario.docs
        ],
    }


if __name__ == "__main__":
    write_dataset(Path(sys.argv[1] if len(sys.argv) > 1 else "eval/data/dev"))
