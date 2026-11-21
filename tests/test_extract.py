import json
from types import SimpleNamespace

import pytest

from acceptguard.extract import MODEL_ID, ExtractionError, cache_key, extract

PAYLOAD = json.dumps(
    {
        "doc_type": "challan",
        "invoice_ref": "INV-1",
        "delivery": {"date_text": "02/03/2026", "iso_date": "2026-03-02", "quote": "RECEIVED 02/03/2026"},
        "objection_raised": {},
        "objection_recorded": {},
        "objection_removed": {},
    }
)


class FakeClient:
    def __init__(self, text: str | None = PAYLOAD):
        self.calls: list[dict] = []
        self.models = self
        self._text = text

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        usage = SimpleNamespace(prompt_token_count=1200, candidates_token_count=90)
        return SimpleNamespace(text=self._text, usage_metadata=usage)


@pytest.fixture
def challan(tmp_path):
    path = tmp_path / "challan.txt"
    path.write_text("RECEIVED 02/03/2026")
    return path


def test_extract_parses_and_caches(challan, tmp_path):
    client = FakeClient()
    first = extract(challan, client=client, cache_dir=tmp_path / "cache")
    second = extract(challan, client=client, cache_dir=tmp_path / "cache")
    assert first.extraction.delivery.date_text == "02/03/2026"
    assert second.extraction == first.extraction
    assert len(client.calls) == 1
    assert second.cached and not first.cached
    assert first.prompt_tokens == 1200


def test_extract_uses_pinned_model_and_no_sampling_parameters(challan, tmp_path):
    client = FakeClient()
    extract(challan, client=client, cache_dir=tmp_path)
    call = client.calls[0]
    assert call["model"] == MODEL_ID == "gemini-3.5-flash-lite"
    config = call["config"]
    assert config.temperature is None and config.top_p is None and config.top_k is None
    assert config.response_mime_type == "application/json"


def test_invalid_model_output_raises_and_is_not_cached(challan, tmp_path):
    with pytest.raises(ExtractionError):
        extract(challan, client=FakeClient("{not json"), cache_dir=tmp_path)
    assert not list(tmp_path.glob("*.json"))


def test_empty_model_output_raises(challan, tmp_path):
    with pytest.raises(ExtractionError):
        extract(challan, client=FakeClient(None), cache_dir=tmp_path)


def test_cache_key_changes_with_file_prompt_and_model():
    base = cache_key(b"doc", "prompt", "model-a")
    assert base != cache_key(b"doc2", "prompt", "model-a")
    assert base != cache_key(b"doc", "prompt v2", "model-a")
    assert base != cache_key(b"doc", "prompt", "model-b")
    assert base == cache_key(b"doc", "prompt", "model-a")
