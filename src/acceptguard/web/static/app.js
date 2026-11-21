"use strict";
// All server text is inserted with textContent via el(); nothing from documents is ever parsed as HTML.

const $ = (sel) => document.querySelector(sel);
const resultBox = $("#result");
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
let current = null; // last result, for export
let sampleList = [];
let busy = false;

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else node.setAttribute(key, value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

function fmt(iso) {
  if (!iso) return "—";
  const [y, m, d] = iso.split("-").map(Number);
  return `${String(d).padStart(2, "0")} ${MONTHS[m - 1]} ${y}`;
}

// Highlight the cited date inside its quote without using innerHTML.
function quoteNode(quote, dateText) {
  const q = el("q");
  if (!quote) return q;
  const i = dateText ? quote.toLowerCase().indexOf(dateText.toLowerCase()) : -1;
  if (i < 0) { q.textContent = quote; return q; }
  q.append(quote.slice(0, i), el("mark", { text: quote.slice(i, i + dateText.length) }), quote.slice(i + dateText.length));
  return q;
}

async function loadSamples() {
  const [samples, meta] = await Promise.all([
    fetch("/api/samples").then((r) => r.json()),
    fetch("/api/meta").then((r) => r.json()).catch(() => null),
  ]);
  sampleList = samples;
  const box = $("#samples");
  box.replaceChildren(...samples.map((s) => el("button", { class: "sample", type: "button", role: "listitem", "aria-pressed": "false", "data-id": s.id },
    el("span", { class: "kicker", text: s.journey }),
    el("span", { class: "t", text: s.title }),
    el("span", { class: "b", text: s.blurb }))));
  box.addEventListener("click", (event) => {
    const button = event.target.closest(".sample");
    if (button) runSample(button.dataset.id);
  });
  if (meta) $("#foot-meta").textContent = `Not tax advice. Synthetic demo data. Extraction model ${meta.model}, prompt ${meta.prompt_sha256}.`;
}

function setBusy(on) {
  busy = on;
  document.querySelectorAll(".sample, #upload-btn").forEach((b) => { b.disabled = on; });
}

function showLoading(fileCount) {
  const started = Date.now();
  const timer = el("span", { text: "0 s" });
  resultBox.replaceChildren(el("div", { class: "loading" },
    el("p", { class: "empty-title" }, "Analyzing evidence… ", timer),
    el("div", { class: "bar", "aria-hidden": "true" }),
    el("ul", {},
      el("li", { text: `Gemini reads each of ${fileCount} document${fileCount === 1 ? "" : "s"} (usually 2–10 s each; first runs are slower).` }),
      el("li", { text: "Every quoted date is then checked word-for-word against the file, with Tesseract OCR for images." }),
      el("li", { text: "Python applies the MSMED rules. Nothing is guessed if a check fails." }))));
  const id = setInterval(() => { timer.textContent = `${Math.round((Date.now() - started) / 1000)} s`; }, 1000);
  return () => clearInterval(id);
}

async function request(url, options, fileCount, previews) {
  if (busy) return;
  setBusy(true);
  const stop = showLoading(fileCount);
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 240000);
  try {
    const response = await fetch(url, { ...options, signal: controller.signal });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(typeof body.detail === "string" ? body.detail : `Request failed (${response.status}).`);
    current = body;
    render(body, previews);
  } catch (error) {
    const message = error.name === "AbortError" ? "The analysis took longer than 4 minutes and was stopped. Nothing was computed." : error.message;
    resultBox.replaceChildren(el("div", { class: "err" }, el("h3", { text: "Could not complete the review" }), el("p", { text: message }),
      el("p", { class: "hint", text: "No result is shown rather than a guessed one. Try again in a minute." })));
  } finally {
    clearTimeout(timeout);
    stop();
    setBusy(false);
  }
}

function runSample(id) {
  const sample = sampleList.find((s) => s.id === id);
  document.querySelectorAll(".sample").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.id === id)));
  const previews = Object.fromEntries(sample.files.map((name) => [name, `/api/samples/${id}/files/${encodeURIComponent(name)}`]));
  request(`/api/samples/${id}/analyze`, { method: "POST" }, sample.files.length, previews);
  if (window.matchMedia("(max-width: 980px)").matches) resultBox.scrollIntoView({ behavior: "smooth", block: "start" });
}

function verdictText(r) {
  if (r.status === "COMPUTED") {
    if (r.decision === "ALLOWED") return ["Deductible this year", "candidate"];
    if (r.decision === "PENDING") return ["Not yet due", "payment pending"];
    return ["Disallowance candidate", "s.43B(h)"];
  }
  if (r.status === "ABSTAIN") return ["Accountant review", "no conclusion"];
  return ["Out of scope", "not computed"];
}

function render(r, previews) {
  const [stampMain, stampSub] = verdictText(r);
  const inv = r.invoice;
  const parts = [];
  parts.push(el("div", { class: "verdict" },
    el("div", { class: `stamp st-${r.status} d-${r.decision || "none"}`, role: "img", "aria-label": `${stampMain}, ${stampSub}` }, stampMain, el("small", { text: stampSub })),
    el("div", {},
      el("h3", { text: r.headline }),
      el("p", { class: "sub", text: `${inv.invoice_no} · ${inv.vendor} (${inv.vendor_category}) · invoice ${fmt(inv.invoice_date)} · ₹${Number(inv.amount).toLocaleString("en-IN")}` }),
      r.ledger_label && r.status === "COMPUTED"
        ? el("span", { class: "compare", text: r.changed ? `Evidence changes the answer: a ledger-only check says “${r.ledger_label}”.` : `Same answer as a ledger-only check (${r.ledger_label}).` })
        : null)));

  if (r.reasons.length || r.notes.length) {
    parts.push(el("section", { class: "block" }, el("h4", { text: r.reasons.length ? "Why this was flagged" : "Worth knowing" }),
      r.reasons.map((x) => el("div", { class: "why" }, el("b", { text: x.title }), el("p", { text: x.explanation }),
        x.detail ? el("p", {}, el("code", { text: x.detail })) : null)),
      r.notes.map((n) => el("p", { class: "note", text: n }))));
  }

  parts.push(el("section", { class: "block" }, el("h4", { text: "Timeline (verified dates only)" }),
    el("ol", { class: "timeline" }, r.timeline.map((t) => el("li", { class: `k-${t.kind}` },
      el("time", { datetime: t.date, text: fmt(t.date) }), el("i", { class: "dot", "aria-hidden": "true" }), el("span", { text: t.label }))))));

  if (r.result) {
    parts.push(el("section", { class: "block" }, el("h4", { text: "Deterministic calculation" }),
      el("dl", { class: "calc" },
        el("div", {}, el("dt", { text: "Acceptance day" }), el("dd", { text: fmt(r.result.acceptance_day) })),
        el("div", {}, el("dt", { text: r.result.due_dates.length > 1 ? "Payment deadline (both readings)" : "Payment deadline" }), el("dd", { text: r.result.due_dates.map(fmt).join(" / ") })),
        el("div", {}, el("dt", { text: "Paid" }), el("dd", { text: inv.payment_date ? fmt(inv.payment_date) : `Unpaid at ${fmt(r.period.as_of)}` })),
        el("div", {}, el("dt", { text: "Financial year end" }), el("dd", { text: fmt(r.period.fy_end) }))),
      r.result.assumptions.map((a) => el("p", { class: "assume", text: `Assumption: ${a.explanation}` }))));
  }

  parts.push(el("section", { class: "block" }, el("h4", { text: `Evidence (${r.documents.length} file${r.documents.length === 1 ? "" : "s"} read)` }),
    r.documents.length ? r.documents.map((d) => docCard(d, previews[d.name])) : el("p", { class: "hint", text: "No evidence files were provided." })));

  parts.push(el("section", { class: "block" },
    el("div", { class: "actions" },
      el("button", { class: "btn", type: "button", id: "export-md", text: "Download workpaper (.md)" }),
      el("button", { class: "btn", type: "button", id: "export-print", text: "Print / save PDF" })),
    el("p", { class: "disc", text: r.disclaimer })));

  resultBox.replaceChildren(...parts);
  $("#export-md").addEventListener("click", exportMarkdown);
  $("#export-print").addEventListener("click", () => window.print());
}

function docCard(d, preview) {
  const isImage = preview && /\.(png|jpe?g)$/i.test(d.name);
  const facts = [];
  if (d.error) facts.push(el("div", { class: "fact" }, el("span", { class: "no", text: d.error.title }), el("div", { class: "why-small", text: d.error.detail })));
  for (const p of d.problems) facts.push(el("div", { class: "fact" }, el("span", { class: "no", text: p.title }), el("div", { class: "why-small", text: p.explanation })));
  for (const f of d.facts) {
    facts.push(el("div", { class: "fact" },
      el("div", { class: "fact-top" }, el("span", { text: f.label }),
        f.verified ? el("span", { class: "ok", text: `✓ Verified · ${fmt(f.value)}` }) : el("span", { class: "no", text: "✗ Not used" })),
      quoteNode(f.quote, f.date_text),
      f.verified && f.source === "email Date header" ? el("div", { class: "hint", text: "Date taken from the email's Date header by Python, not from the model." }) : null,
      !f.verified && f.check ? el("div", { class: "why-small", text: `${f.check.title}: ${f.check.explanation}` }) : null));
  }
  if (d.credit) {
    facts.push(el("div", { class: "fact" },
      el("div", { class: "fact-top" }, el("span", { text: `Payment terms: ${d.credit.days ?? "?"} days from ${d.credit.basis || "unspecified"}` }),
        d.credit.verified ? el("span", { class: "ok", text: "✓ Verified" }) : el("span", { class: "no", text: "✗ Not used" })),
      quoteNode(d.credit.quote, d.credit.days ? String(d.credit.days) : null),
      !d.credit.verified && d.credit.check ? el("div", { class: "why-small", text: d.credit.check.explanation }) : null));
  }
  if (!facts.length) facts.push(el("p", { class: "hint", text: "No dates or payment terms reported for this file." }));
  if (d.illegible.length) facts.push(el("p", { class: "hint", text: `Model marked as illegible: ${d.illegible.join("; ")}` }));
  return el("article", { class: "doc" },
    el("div", { class: "doc-head" }, el("b", { text: d.name }),
      el("span", { class: "tag", text: [d.doc_type, d.objection_medium && d.objection_medium !== d.doc_type ? `${d.objection_medium} objection` : null].filter(Boolean).join(" · ") })),
    el("div", { class: `doc-body${isImage ? "" : " noimg"}` },
      isImage ? el("a", { href: preview, target: "_blank", rel: "noopener" }, el("img", { class: "thumb", src: preview, alt: `Preview of ${d.name}`, loading: "lazy" })) : null,
      el("div", {}, facts)));
}

function exportMarkdown() {
  const r = current;
  if (!r) return;
  const inv = r.invoice;
  const lines = [
    `# AcceptGuard workpaper: ${inv.invoice_no}`, "",
    `> ${r.disclaimer}`, "",
    `- Vendor: ${inv.vendor} (${inv.vendor_category})`,
    `- Invoice date: ${inv.invoice_date} · Amount: ${inv.amount} · Paid: ${inv.payment_date || "unpaid"}`,
    `- Financial year end: ${r.period.fy_end} · Status as of: ${r.period.as_of}`,
    `- Status: **${r.status}**${r.decision ? ` · ${r.decision_label}` : ""}${r.ledger_label ? ` · ledger-only check: ${r.ledger_label}` : ""}`, "",
    `## Summary`, r.headline, "",
  ];
  if (r.reasons.length) lines.push("## Routed to review because", ...r.reasons.map((x) => `- **${x.title}** (${x.code}): ${x.explanation}${x.detail ? ` _${x.detail}_` : ""}`), "");
  if (r.result) lines.push("## Calculation", `- Acceptance day: ${r.result.acceptance_day}`, `- Payment deadline: ${r.result.due_dates.join(" / ")}`, ...r.result.assumptions.map((a) => `- Assumption: ${a.explanation}`), "");
  lines.push("## Timeline", ...r.timeline.map((t) => `- ${t.date}: ${t.label}`), "");
  lines.push("## Evidence");
  for (const d of r.documents) {
    lines.push(`### ${d.name}`);
    for (const f of d.facts) lines.push(`- ${f.label}: ${f.verified ? `verified ${f.value}` : `not used (${f.check ? f.check.code : "unverified"})`} — "${f.quote || ""}"`);
    if (d.credit) lines.push(`- Payment terms: ${d.credit.days} days from ${d.credit.basis} — ${d.credit.verified ? "verified" : "not used"} — "${d.credit.quote || ""}"`);
    for (const p of d.problems) lines.push(`- ${p.title} (${p.code})`);
  }
  lines.push("", "## Reviewer sign-off", "- Reviewed by: ____________________  Date: __________", "- Conclusion: ____________________");
  const blob = new Blob([lines.join("\n")], { type: "text/markdown" });
  const link = el("a", { href: URL.createObjectURL(blob), download: `acceptguard-${inv.invoice_no}.md` });
  document.body.append(link);
  link.click();
  link.remove();
}

// Upload form
const fileInput = $("#files");
const drop = $("#drop");
let chosen = [];
function showFiles() {
  $("#file-list").replaceChildren(...chosen.map((f) => el("li", {}, el("span", { text: f.name }), el("span", { text: `${(f.size / 1024).toFixed(0)} KB` }))));
}
fileInput.addEventListener("change", () => { chosen = [...fileInput.files].slice(0, 6); showFiles(); });
["dragenter", "dragover"].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.add("over"); }));
["dragleave", "drop"].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
drop.addEventListener("drop", (e) => { chosen = [...e.dataTransfer.files].slice(0, 6); showFiles(); });

$("#upload-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  if (!form.reportValidity()) return;
  if (!chosen.length) { $("#drop-text").textContent = "Add at least one evidence file first."; return; }
  const data = new FormData(form);
  data.delete("files");
  chosen.forEach((f) => data.append("files", f, f.name));
  const previews = {};
  chosen.forEach((f, i) => {
    const ext = f.name.slice(f.name.lastIndexOf(".")).toLowerCase();
    const stem = f.name.slice(0, f.name.lastIndexOf(".")).replace(/[^A-Za-z0-9_.-]+/g, "-").replace(/^[-.]+|[-.]+$/g, "").slice(0, 40) || "file";
    previews[`${String(i + 1).padStart(2, "0")}-${stem}${ext}`] = URL.createObjectURL(f); // mirrors the server's safe name
  });
  document.querySelectorAll(".sample").forEach((b) => b.setAttribute("aria-pressed", "false"));
  request("/api/analyze", { method: "POST", body: data }, chosen.length, previews);
});

loadSamples().catch(() => {
  $("#samples").replaceChildren(el("p", { class: "hint", text: "Samples could not be loaded. Check the server is running." }));
});
