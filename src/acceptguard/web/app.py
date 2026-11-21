"""AcceptGuard web app: uvicorn acceptguard.web.app:app

Gemini is called server-side only. Uploaded files live in a temporary directory for the length of one
request and their extractions are not cached, so no document content is persisted. Samples are synthetic.
"""
import logging
import os
import re
import shutil
import tempfile
import threading
import time
from io import BytesIO
from collections import defaultdict, deque
from datetime import date
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from PIL import Image
from pydantic import ValidationError
from pypdf import PdfReader

from acceptguard.clock import Period
from acceptguard.extract import MODEL_ID, PROMPT_PATH, extract
from acceptguard.ingest import EVIDENCE_SUFFIXES, IMAGE_SUFFIXES, LedgerRow, evidence_files, load_ledger
from acceptguard.pipeline import run_invoice
from acceptguard.web.samples import SAMPLES, Sample
from acceptguard.web.serialize import invoice_json

log = logging.getLogger("acceptguard.web")
ROOT = Path(__file__).resolve().parents[3]
STATIC = Path(__file__).parent / "static"
MAX_FILES = 6
MAX_FILE_BYTES = 8 * 1024 * 1024
RATE_WINDOW_S = 600
RATE_LIMIT = 15  # analyses per client per window
GLOBAL_RATE_LIMIT = 150  # analyses per window across all clients: caps spend on the shared Gemini key
MAX_PDF_PAGES = 10
MAX_IMAGE_PIXELS = 40_000_000
MAX_CONCURRENT = 3
INVOICE_NO_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,39}$")
SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9_.-]+")
MAGIC = {".pdf": (b"%PDF",), ".png": (b"\x89PNG",), ".jpg": (b"\xff\xd8",), ".jpeg": (b"\xff\xd8",)}

app = FastAPI(title="AcceptGuard", docs_url=None, redoc_url=None, openapi_url=None)
_hits: dict[str, deque[float]] = defaultdict(deque)
_hits_lock = threading.Lock()
_slots = threading.BoundedSemaphore(MAX_CONCURRENT)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' blob: data:; style-src 'self' https://fonts.googleapis.com; "
        "font-src https://fonts.gstatic.com; script-src 'self'; connect-src 'self'; frame-ancestors 'none'")
    return response


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "model": MODEL_ID, "tesseract": shutil.which("tesseract") is not None}


@app.get("/api/meta")
def meta() -> dict:
    import hashlib
    return {"model": MODEL_ID, "prompt_sha256": hashlib.sha256(PROMPT_PATH.read_bytes()).hexdigest()[:12],
            "max_files": MAX_FILES, "max_file_mb": MAX_FILE_BYTES // (1024 * 1024)}


@app.get("/api/samples")
def samples() -> list[dict]:
    return [{**s.card(), "files": [p.name for p in _sample_files(s)], "invoice": _sample_row(s).model_dump(mode="json"),
             "period": {"fy_end": s.fy_end.isoformat(), "as_of": s.as_of.isoformat()}} for s in SAMPLES.values()]


@app.get("/api/samples/{sample_id}/files/{name}")
def sample_file(sample_id: str, name: str) -> FileResponse:
    sample = _sample(sample_id)
    match = next((p for p in _sample_files(sample) if p.name == name), None)  # whitelist, never join user paths
    if match is None:
        raise HTTPException(404, "No such file")
    return FileResponse(match)


@app.post("/api/samples/{sample_id}/analyze")
def analyze_sample(sample_id: str, request: Request) -> dict:
    sample = _sample(sample_id)
    _rate_limit(request)
    period = Period(sample.fy_end, sample.as_of)
    with _slot():
        run = run_invoice(_sample_row(sample), ROOT / sample.dataset / "evidence", period)
    return invoice_json(run, period)


@app.post("/api/analyze")
async def analyze_upload(
    request: Request,
    invoice_no: str = Form(...), vendor: str = Form("Vendor"), vendor_category: str = Form(...),
    invoice_date: str = Form(...), amount: str = Form(...), credit_days: str = Form(""),
    payment_date: str = Form(""), paid_amount: str = Form(""), fy_end: str = Form(...), as_of: str = Form(...),
    files: list[UploadFile] = File(...),
) -> dict:
    _rate_limit(request)
    if not INVOICE_NO_RE.fullmatch(invoice_no):
        raise HTTPException(422, "Invoice number: letters, digits, '.', '_' or '-' only (max 40).")
    if payment_date and not paid_amount:
        paid_amount = amount  # the form treats a payment date as full payment unless an amount is given
    try:
        row = LedgerRow.model_validate({"invoice_no": invoice_no, "vendor": vendor[:80], "vendor_category": vendor_category,
                                        "invoice_date": invoice_date, "amount": amount, "credit_days": credit_days,
                                        "paid_amount": paid_amount, "payment_date": payment_date})
        period = Period(date.fromisoformat(fy_end), date.fromisoformat(as_of))
    except (ValidationError, ValueError) as error:
        raise HTTPException(422, f"Check the invoice fields: {_first_error(error)}") from None
    if not 1 <= len(files) <= MAX_FILES:
        raise HTTPException(422, f"Upload between 1 and {MAX_FILES} evidence files.")
    with tempfile.TemporaryDirectory(prefix="acceptguard-") as tmp:
        folder = Path(tmp) / "evidence" / invoice_no
        folder.mkdir(parents=True)
        for index, upload in enumerate(files):
            await _save(upload, folder, index)
        cache = Path(tmp) / "cache"  # per-request cache: extractions of uploads are never persisted

        def extractor(path: Path):
            return extract(path, cache_dir=cache).extraction

        def work() -> dict:  # blocking Gemini + OCR work runs off the event loop
            with _slot():
                return invoice_json(run_invoice(row, Path(tmp) / "evidence", period, extractor=extractor), period)

        return await run_in_threadpool(work)


@app.exception_handler(Exception)
async def unexpected(_request: Request, error: Exception) -> JSONResponse:
    log.exception("unhandled error: %s", type(error).__name__)  # no document content is logged
    return JSONResponse({"detail": "Something went wrong on the server. Nothing was computed."}, status_code=500)


async def _save(upload: UploadFile, folder: Path, index: int) -> None:
    original = upload.filename or "file"
    suffix = Path(original).suffix.lower()
    if suffix not in EVIDENCE_SUFFIXES:
        raise HTTPException(415, f"{original[:60]}: allowed types are {', '.join(sorted(EVIDENCE_SUFFIXES))}.")
    data = await upload.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise HTTPException(413, f"{original[:60]}: larger than {MAX_FILE_BYTES // (1024 * 1024)} MB.")
    if not data:
        raise HTTPException(422, f"{original[:60]}: file is empty.")
    if suffix in MAGIC and not data.startswith(MAGIC[suffix]):
        raise HTTPException(415, f"{original[:60]}: contents do not match the {suffix} type.")
    _check_decoded_size(data, suffix, original[:60])
    stem = SAFE_NAME_RE.sub("-", Path(original).stem).strip("-.")[:40] or "file"
    (folder / f"{index + 1:02d}-{stem}{suffix}").write_bytes(data)  # server-chosen name: no path traversal


def _client_id(request: Request) -> str:
    """Behind a trusted proxy (TRUST_PROXY=1, set on Render) the rightmost X-Forwarded-For entry is the one the
    proxy appended. Without one, any forwarded header is client-controlled, so only the socket address counts."""
    peer = request.client.host if request.client else "unknown"
    if os.environ.get("TRUST_PROXY") != "1":
        return f"client:{peer}"
    forwarded = [part.strip() for part in request.headers.get("x-forwarded-for", "").split(",") if part.strip()]
    return f"client:{forwarded[-1] if forwarded else peer}"


def _check_decoded_size(data: bytes, suffix: str, label: str) -> None:
    """Bound the work a small upload can cause: decompression bombs, huge images, very long PDFs."""
    try:
        if suffix in IMAGE_SUFFIXES:
            with Image.open(BytesIO(data)) as image:
                if image.width * image.height > MAX_IMAGE_PIXELS:
                    raise HTTPException(413, f"{label}: image is too large to process.")
        elif suffix == ".pdf" and len(PdfReader(BytesIO(data)).pages) > MAX_PDF_PAGES:
            raise HTTPException(413, f"{label}: PDFs are limited to {MAX_PDF_PAGES} pages.")
    except HTTPException:
        raise
    except Exception:  # unreadable or bomb-like files are rejected, never processed
        raise HTTPException(415, f"{label}: file could not be read.") from None


def _rate_limit(request: Request) -> None:
    now = time.monotonic()
    with _hits_lock:
        for key in [k for k, v in _hits.items() if not v or now - v[-1] > RATE_WINDOW_S]:
            del _hits[key]  # forget idle clients so the table cannot grow without bound
        everyone = _hits["global"]
        mine = _hits[_client_id(request)]
        for hits in (everyone, mine):
            while hits and now - hits[0] > RATE_WINDOW_S:
                hits.popleft()
        if len(mine) >= RATE_LIMIT or len(everyone) >= GLOBAL_RATE_LIMIT:
            raise HTTPException(429, "Demo limit reached: try again in a few minutes.", headers={"Retry-After": "120"})
        mine.append(now)
        everyone.append(now)


class _slot:
    """Bound concurrent Gemini work so one visitor cannot exhaust the shared quota."""

    def __enter__(self) -> None:
        if not _slots.acquire(timeout=30):
            raise HTTPException(503, "The demo is busy. Try again in a moment.", headers={"Retry-After": "30"})

    def __exit__(self, *_exc: object) -> None:
        _slots.release()


def _sample(sample_id: str) -> Sample:
    if sample_id not in SAMPLES:
        raise HTTPException(404, "No such sample")
    return SAMPLES[sample_id]


def _sample_row(sample: Sample) -> LedgerRow:
    return next(r for r in load_ledger(ROOT / sample.dataset / "ledger.csv") if r.invoice_no == sample.invoice_no)


def _sample_files(sample: Sample) -> list[Path]:
    return evidence_files(ROOT / sample.dataset / "evidence", sample.invoice_no)


def _first_error(error: Exception) -> str:
    if isinstance(error, ValidationError):
        first = error.errors()[0]
        return f"{'.'.join(map(str, first['loc']))}: {first['msg']}"
    return str(error)


app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
