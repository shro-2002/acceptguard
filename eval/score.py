"""Score the full pipeline on a labelled synthetic set with the real model.

    PYTHONPATH=src uv run --env-file .env python eval/score.py eval/data/dev --ocr simulated

--ocr simulated: image text comes from the labels (isolates model extraction; OCR not tested).
--ocr tesseract: real OCR (needs `brew install tesseract`).
Labels come from the generator spec, never from model output.
"""
import argparse
import hashlib
import json
from datetime import date, datetime
from pathlib import Path

from acceptguard.clock import Period
from acceptguard.extract import MODEL_ID, PROMPT_PATH, ExtractionRecord, extract
from acceptguard.ingest import source_text
from acceptguard.models import DocExtraction
from acceptguard.pipeline import run

DATE_FIELDS = ("delivery", "objection_raised", "objection_removed")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("data", type=Path)
    parser.add_argument("--ocr", choices=("simulated", "tesseract"), required=True)
    args = parser.parse_args()
    labels = json.loads((args.data / "labels.json").read_text())
    docs = {(inv["invoice_no"], doc["file"]): doc for inv in labels["invoices"] for doc in inv["docs"]}
    records: dict[Path, ExtractionRecord] = {}

    def extractor(path: Path) -> DocExtraction:
        records[path] = extract(path)
        return records[path].extraction

    def reader(path: Path):
        if args.ocr == "tesseract":
            return source_text(path)
        doc = docs[(path.parent.name, path.name)]
        text = doc["simulated_ocr"] if doc["simulated_ocr"] is not None else doc["text"]
        return source_text(path, ocr=lambda _image: text)

    period = Period(date.fromisoformat(labels["fy_end"]), date.fromisoformat(labels["as_of"]))
    runs = {r.outcome.invoice_no: r.outcome for r in run(args.data / "ledger.csv", args.data / "evidence", period,
                                                          extractor=extractor, reader=reader)}
    cases = [_score_case(inv, runs[inv["invoice_no"]]) for inv in labels["invoices"]]
    fields = _score_fields(records, docs)
    summary = _summary(cases, fields, records)
    _print(cases, summary)
    out = Path("eval/results") / f"{args.data.name}-{args.ocr}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    meta = {"model_id": MODEL_ID, "prompt_sha256": hashlib.sha256(PROMPT_PATH.read_bytes()).hexdigest()[:12],
            "ocr": args.ocr, "run_at": datetime.now().isoformat(timespec="seconds"), "data": str(args.data)}
    out.write_text(json.dumps({"meta": meta, "summary": summary, "cases": cases, "fields": fields}, indent=2))
    print(f"\nwritten {out}")


def _score_case(label: dict, outcome) -> dict:
    expected, got = label["expected_status"], outcome.status
    reason = outcome.reasons[0].code if outcome.reasons else None
    if expected == "OUT_OF_SCOPE":
        verdict = "ok" if got == "OUT_OF_SCOPE" else "wrong"
    elif got == "COMPUTED":
        verdict = "ok" if expected == "COMPUTED" and outcome.decision == label["expected_decision"] else "FALSE_CONFIDENT"
    elif expected == "ABSTAIN":
        verdict = "ok" if reason == label["expected_reason"] else "abstained_other_reason"
    else:
        verdict = "unnecessary_abstention"
    return {"invoice_no": label["invoice_no"], "title": label["title"], "expected": expected,
            "expected_decision": label["expected_decision"], "expected_reason": label["expected_reason"],
            "got": got, "decision": outcome.decision, "reason": reason, "verdict": verdict,
            "detail": outcome.reasons[0].detail if outcome.reasons else ""}


def _score_fields(records: dict[Path, ExtractionRecord], docs: dict) -> dict:
    """Field-level date match on non-null ground truth: correct, wrong value, or missed (null)."""
    tally = {name: {"correct": 0, "wrong": 0, "missed": 0} for name in (*DATE_FIELDS, "credit_days", "objection_recorded")}
    for path, record in records.items():
        truth = DocExtraction.model_validate(docs[(path.parent.name, path.name)]["expected"])
        got = record.extraction
        for name in DATE_FIELDS:
            want, have = getattr(truth, name).iso_date, getattr(got, name).iso_date
            if want is not None:
                tally[name]["correct" if have == want else "missed" if have is None else "wrong"] += 1
        if truth.credit_days is not None:
            tally["credit_days"]["correct" if got.credit_days == truth.credit_days else "wrong"] += 1
        if truth.objection_recorded.quote is not None:  # date comes from the email header; score presence
            tally["objection_recorded"]["correct" if got.objection_recorded.quote else "missed"] += 1
    return tally


def _summary(cases: list[dict], fields: dict, records: dict) -> dict:
    scored = [c for c in cases if c["expected"] != "OUT_OF_SCOPE"]
    computed = [c for c in scored if c["got"] == "COMPUTED"]
    expected_abstain = [c for c in scored if c["expected"] == "ABSTAIN"]
    tokens_in = sum(r.prompt_tokens or 0 for r in records.values())
    tokens_out = sum(r.output_tokens or 0 for r in records.values())
    return {
        "invoices_scored": len(scored),
        "false_confident": sum(c["verdict"] == "FALSE_CONFIDENT" for c in scored),
        "computed": len(computed),
        "computed_correct": sum(c["verdict"] == "ok" for c in computed),
        "abstained": sum(c["got"] == "ABSTAIN" for c in scored),
        "abstention_recall": f'{sum(c["got"] == "ABSTAIN" for c in expected_abstain)}/{len(expected_abstain)}',
        "unnecessary_abstentions": sum(c["verdict"] == "unnecessary_abstention" for c in scored),
        "documents_extracted": len(records),
        "cache_hits": sum(r.cached for r in records.values()),
        "tokens_in_out": [tokens_in, tokens_out],
        "fields": fields,
    }


def _print(cases: list[dict], summary: dict) -> None:
    for c in cases:
        got = c["decision"] or c["reason"] or c["got"]
        want = c["expected_decision"] or c["expected_reason"] or c["expected"]
        print(f'{c["invoice_no"]}  {c["verdict"]:<24} want {want:<22} got {got:<22} {c["detail"][:70]}')
    print()
    for key, value in summary.items():
        print(f"{key:>24}: {value}")


if __name__ == "__main__":
    main()
