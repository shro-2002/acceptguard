"""acceptguard LEDGER EVIDENCE_DIR --fy-end YYYY-MM-DD --as-of YYYY-MM-DD [--out DIR]"""
import argparse
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from acceptguard.clock import Period
from acceptguard.extract import MODEL_ID
from acceptguard.pipeline import run
from acceptguard.report import write_csv, write_html


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="acceptguard", description="Evidence-backed MSME acceptance dates for CA review.")
    parser.add_argument("ledger", type=Path, help="AP ledger CSV with ISO dates")
    parser.add_argument("evidence", type=Path, help="folder with one subfolder per invoice number")
    parser.add_argument("--fy-end", type=date.fromisoformat, required=True, help="financial year end, e.g. 2026-03-31")
    parser.add_argument("--as-of", type=date.fromisoformat, required=True, help="status date for unpaid invoices")
    parser.add_argument("--out", type=Path, default=Path("out"), help="output folder (default: out)")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    period = Period(fy_end=args.fy_end, as_of=args.as_of)
    runs = run(args.ledger, args.evidence, period)
    args.out.mkdir(parents=True, exist_ok=True)
    write_html(runs, args.out / "report.html", period, MODEL_ID)
    write_csv(runs, args.out / "report.csv")
    counts = {status: sum(r.outcome.status == status for r in runs) for status in ("COMPUTED", "ABSTAIN", "OUT_OF_SCOPE")}
    print(f"{len(runs)} invoices: {counts}. Report: {args.out / 'report.html'}")
    return 0
