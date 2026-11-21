"""One Gemini call per document, cached on disk. The model only extracts; nothing here decides."""
import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from acceptguard.ingest import email_view
from acceptguard.models import DocExtraction

MODEL_ID = "gemini-3.5-flash-lite"
PROMPT_PATH = Path(__file__).parent / "prompts" / "extract_v2.md"
DEFAULT_CACHE_DIR = Path(".cache/extractions")
TIMEOUT_MS = 60_000  # a hung request becomes an ExtractionError instead of blocking the run
RETRY_INITIAL_DELAY_S = 10.0  # 429 quotas are per minute; the SDK default of 1s retries too fast
MIME_TYPES = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".txt": "text/plain",
    ".eml": "text/plain",
}


class ExtractionError(RuntimeError):
    pass


class ExtractionRecord(BaseModel):
    extraction: DocExtraction
    model_id: str
    prompt_tokens: int | None = None
    output_tokens: int | None = None
    cached: bool = False


def cache_key(file_bytes: bytes, prompt: str, model_id: str) -> str:
    """Changes whenever the file, prompt, model or extraction schema changes."""
    schema = json.dumps(DocExtraction.model_json_schema(), sort_keys=True)
    digest = hashlib.sha256()
    for part in (file_bytes, model_id.encode(), prompt.encode(), schema.encode()):
        digest.update(hashlib.sha256(part).digest())
    return digest.hexdigest()


def model_input(path: Path) -> bytes:
    """Bytes sent to the model. Emails are decoded first so quoted-printable never reaches it."""
    raw = path.read_bytes()
    return email_view(raw).encode("utf-8") if path.suffix.lower() == ".eml" else raw


def extract(path: Path, *, client: Any = None, cache_dir: Path = DEFAULT_CACHE_DIR, model_id: str = MODEL_ID) -> ExtractionRecord:
    data = model_input(path)
    prompt = PROMPT_PATH.read_text(encoding="utf-8")
    cached_file = cache_dir / f"{cache_key(data, prompt, model_id)}.json"
    if cached_file.exists():
        record = ExtractionRecord.model_validate_json(cached_file.read_text(encoding="utf-8"))
        return record.model_copy(update={"cached": True})
    record = _call_model(data, path, prompt, model_id, client)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached_file.write_text(record.model_dump_json(), encoding="utf-8")
    return record


def _call_model(data: bytes, path: Path, prompt: str, model_id: str, client: Any) -> ExtractionRecord:
    from google import genai
    from google.genai import errors, types

    try:
        client = client or genai.Client(http_options=types.HttpOptions(timeout=TIMEOUT_MS, retry_options=types.HttpRetryOptions(attempts=5, initial_delay=RETRY_INITIAL_DELAY_S)))
        response = client.models.generate_content(
            model=model_id,
            contents=[types.Part.from_bytes(data=data, mime_type=MIME_TYPES[path.suffix.lower()])],
            config=types.GenerateContentConfig(
                system_instruction=prompt,
                response_mime_type="application/json",
                response_schema=DocExtraction,
            ),
        )
    except (ValueError, errors.APIError) as error:  # ValueError: no API key configured
        raise ExtractionError(f"{path.name}: Gemini call failed: {error}") from error
    if not response.text:
        raise ExtractionError(f"{path.name}: model returned no text")
    try:
        extraction = DocExtraction.model_validate_json(response.text)
    except ValidationError as error:
        raise ExtractionError(f"{path.name}: model output failed schema validation") from error
    usage = response.usage_metadata
    return ExtractionRecord(
        extraction=extraction,
        model_id=model_id,
        prompt_tokens=getattr(usage, "prompt_token_count", None),
        output_tokens=getattr(usage, "candidates_token_count", None),
    )
