"""Self-contained HTML review sheet and a CSV of the same outcomes. All evidence text is escaped."""
import base64
import csv
from decimal import Decimal
from html import escape
from pathlib import Path

from acceptguard.clock import Period
from acceptguard.pipeline import InvoiceRun

THUMBNAIL_SUFFIXES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}
STATUS_LABEL = {"COMPUTED": "Computed", "ABSTAIN": "Routed to CA", "OUT_OF_SCOPE": "Out of scope"}
DISCLAIMER = (
    "Candidates for review only, not tax advice. A chartered accountant must review every line. "
    "Interpretations marked [CA] in interpretations.py are unconfirmed."
)

CSS = """
:root { --bg:#f7f5f0; --card:#fffdf8; --ink:#1d1b16; --muted:#6b6457; --line:#e2dccf;
  --ok:#1f6b45; --bad:#a3271f; --ca:#8a5a00; --scope:#55606e; --accent:#2b4c7e; }
@media (prefers-color-scheme: dark) { :root { --bg:#16140f; --card:#1f1c16; --ink:#efe9dc; --muted:#a59d8c;
  --line:#3a352b; --ok:#6fcf9a; --bad:#f08a80; --ca:#e8b450; --scope:#9aa6b4; --accent:#8fb0e3; } }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--ink); font:15px/1.55 ui-sans-serif, system-ui, sans-serif; }
main { max-width:980px; margin:0 auto; padding:32px 16px 64px; }
h1 { font:600 28px/1.2 ui-serif, Georgia, serif; margin:0 0 4px; letter-spacing:-0.01em; }
.meta, .disclaimer { color:var(--muted); font-size:13px; }
.disclaimer { border-left:3px solid var(--ca); padding:6px 10px; margin:16px 0 24px; }
.summary { display:grid; grid-template-columns:repeat(auto-fit, minmax(150px, 1fr)); gap:10px; margin-bottom:28px; }
.stat { background:var(--card); border:1px solid var(--line); border-radius:6px; padding:12px 14px; }
.stat b { display:block; font:600 26px/1 ui-serif, Georgia, serif; }
.stat span { color:var(--muted); font-size:13px; }
details { background:var(--card); border:1px solid var(--line); border-radius:6px; margin-bottom:10px; }
details[open] { border-color:var(--accent); }
summary { cursor:pointer; padding:12px 14px; display:grid; grid-template-columns:110px 1fr auto; gap:12px; align-items:baseline; }
summary:focus-visible { outline:2px solid var(--accent); outline-offset:2px; }
.inv { font-weight:600; font-variant-numeric:tabular-nums; }
.badge { font-size:12px; font-weight:600; padding:2px 8px; border-radius:999px; border:1px solid currentColor; white-space:nowrap; }
.COMPUTED { color:var(--ok); } .ABSTAIN { color:var(--ca); } .OUT_OF_SCOPE { color:var(--scope); }
.ALLOWED { color:var(--ok); } .DISALLOWED { color:var(--bad); } .PENDING { color:var(--ca); }
.changed { color:var(--accent); font-weight:600; font-size:12px; }
.body { padding:0 14px 14px; border-top:1px solid var(--line); }
dl { display:grid; grid-template-columns:150px 1fr; gap:4px 12px; margin:12px 0; }
dt { color:var(--muted); }
blockquote { margin:6px 0; padding:6px 10px; border-left:3px solid var(--line); font-family:ui-monospace, monospace; font-size:13px; }
.reason code { font-weight:600; }
.thumbs { display:flex; flex-wrap:wrap; gap:8px; margin-top:8px; }
.thumbs img { max-width:300px; width:100%; border:1px solid var(--line); border-radius:4px; }
.headline { font-size:13px; color:var(--muted); }
@media (max-width:600px) { summary { grid-template-columns:1fr auto; } summary .headline { grid-column:1 / -1; order:3; } dl { grid-template-columns:1fr; } }
@media print { details { break-inside:avoid; } }
"""


def write_csv(runs: list[InvoiceRun], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["invoice_no", "status", "ledger_decision", "evidence_decision", "changed",
                         "acceptance_day", "due_dates", "reason_codes", "assumptions"])
        for run in runs:
            o, r = run.outcome, run.outcome.result
            writer.writerow([o.invoice_no, o.status, o.ledger_decision or "", o.decision or "", o.changed,
                             r.acceptance_day if r else "", " | ".join(map(str, r.due_dates)) if r else "",
                             " | ".join(a.code for a in o.reasons), " | ".join(r.assumptions) if r else ""])


def write_html(runs: list[InvoiceRun], path: Path, period: Period, model_id: str) -> None:
    ordered = sorted(runs, key=_sort_key)
    cards = "\n".join(_card(run) for run in ordered)
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>AcceptGuard review</title>
<style>{CSS}</style></head><body><main>
<h1>MSME payment review: candidates for CA</h1>
<p class="meta">Year ending {period.fy_end} &middot; status as of {period.as_of} &middot; extraction model {escape(model_id)}</p>
<p class="disclaimer">{escape(DISCLAIMER)}</p>
<section class="summary" aria-label="Summary">{_summary(runs)}</section>
<section aria-label="Invoices">{cards}</section>
</main></body></html>"""
    path.write_text(page, encoding="utf-8")


def _sort_key(run: InvoiceRun) -> tuple[int, str]:
    order = {"ABSTAIN": 1, "COMPUTED": 2, "OUT_OF_SCOPE": 3}
    return (0 if run.outcome.changed else order[run.outcome.status], run.outcome.invoice_no)


def _summary(runs: list[InvoiceRun]) -> str:
    stats = [
        (sum(r.outcome.status == "COMPUTED" for r in runs), "computed from evidence"),
        (sum(r.outcome.changed for r in runs), "differ from ledger"),
        (sum(r.outcome.status == "ABSTAIN" for r in runs), "routed to CA"),
        (sum(r.outcome.status == "OUT_OF_SCOPE" for r in runs), "out of scope"),
    ]
    return "".join(f'<div class="stat"><b>{n}</b><span>{label}</span></div>' for n, label in stats)


def _card(run: InvoiceRun) -> str:
    o, r = run.outcome, run.outcome.result
    decision = f'<span class="{o.decision}">{o.decision}</span>' if o.decision else "&mdash;"
    ledger = f'<span class="{o.ledger_decision}">{o.ledger_decision}</span>' if o.ledger_decision else "&mdash;"
    changed = ' <span class="changed">changed</span>' if o.changed else ""
    rows = [("Vendor", escape(run.row.vendor)), ("Amount", inr(run.row.amount)),
            ("Ledger result", ledger), ("Evidence result", decision + changed)]
    if o.decision:
        headline = f"ledger {ledger} &rarr; evidence {decision}{changed}"
    else:
        headline = escape(o.reasons[0].code) if o.reasons else "&mdash;"
    if r:
        rows += [("Acceptance day", str(r.acceptance_day)), ("Due date", " to ".join(map(str, r.due_dates)))]
        rows += [("Assumptions", escape(", ".join(r.assumptions)))] if r.assumptions else []
    details = "".join(f"<dt>{label}</dt><dd>{value}</dd>" for label, value in rows)
    reasons = "".join(f'<p class="reason"><code>{escape(a.code)}</code> {escape(a.detail)}</p>' for a in o.reasons)
    quotes = "".join(f"<p>{escape(what)}</p><blockquote>{escape(quote)}</blockquote>" for what, quote in o.citations)
    notes = "".join(f"<p>{escape(note)}</p>" for note in o.notes)
    return f"""<details><summary><span class="inv">{escape(o.invoice_no)}</span>
<span class="headline">{headline}</span><span class="badge {o.status}">{STATUS_LABEL[o.status]}</span></summary>
<div class="body"><dl>{details}</dl>{reasons}{quotes}{notes}{_evidence(run.files)}</div></details>"""


def _evidence(files: tuple[Path, ...]) -> str:
    if not files:
        return "<p>No evidence files supplied.</p>"
    names = ", ".join(escape(f.name) for f in files)
    images = "".join(
        f'<img alt="{escape(f.name)}" src="data:{THUMBNAIL_SUFFIXES[f.suffix.lower()]};base64,'
        f'{base64.b64encode(f.read_bytes()).decode()}">'
        for f in files if f.suffix.lower() in THUMBNAIL_SUFFIXES
    )
    return f'<p>Evidence: {names}</p><div class="thumbs">{images}</div>'


def inr(amount: Decimal) -> str:
    """Indian digit grouping: 118000.00 -> ₹1,18,000.00"""
    whole, _, fraction = f"{amount:.2f}".partition(".")
    head, tail = whole[:-3], whole[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return "₹" + ",".join(groups + [tail]) + "." + fraction
