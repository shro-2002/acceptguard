"""Web layer: upload validation, sample whitelisting, and safe behaviour when Gemini fails. No API key needed."""
from datetime import date

import pytest
from fastapi.testclient import TestClient

from acceptguard.extract import ExtractionError, ExtractionRecord
from acceptguard.models import Cited, DocExtraction
from acceptguard.web import app as web

client = TestClient(web.app)
FORM = {"invoice_no": "INV-9", "vendor_category": "micro", "invoice_date": "2026-03-10", "amount": "1000",
        "payment_date": "2026-04-20", "fy_end": "2026-03-31", "as_of": "2026-10-01"}
CHALLAN = b"DELIVERY CHALLAN\nInvoice No: INV-9\nRECEIVED 10 March 2026 - Stores\n"


@pytest.fixture(autouse=True)
def reset_rate_limit():
    web._hits.clear()


def fake_extract(path, cache_dir=None):
    delivery = Cited(date_text="10 March 2026", iso_date=date(2026, 3, 10), quote="RECEIVED 10 March 2026 - Stores")
    empty = {k: Cited() for k in ("objection_raised", "objection_recorded", "objection_removed")}
    return ExtractionRecord(extraction=DocExtraction(doc_type="challan", invoice_ref="INV-9", delivery=delivery, **empty), model_id="fake")


def upload(files, **overrides):
    return client.post("/api/analyze", data={**FORM, **overrides}, files=[("files", f) for f in files])


def test_health_and_security_headers():
    response = client.get("/health")
    assert response.json()["status"] == "ok"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "default-src 'self'" in response.headers["Content-Security-Policy"]


def test_samples_listed_and_files_whitelisted():
    samples = client.get("/api/samples").json()
    assert {s["id"] for s in samples} >= {"written-objection", "prompt-injection"}
    first = samples[0]
    assert client.get(f"/api/samples/{first['id']}/files/{first['files'][0]}").status_code == 200
    assert client.get(f"/api/samples/{first['id']}/files/..%2F..%2Fledger.csv").status_code == 404
    assert client.get("/api/samples/nope/files/x").status_code == 404


def test_upload_computes_with_server_side_extraction(monkeypatch):
    monkeypatch.setattr(web, "extract", fake_extract)
    body = upload([("challan.txt", CHALLAN, "text/plain")]).json()
    assert (body["status"], body["decision"]) == ("COMPUTED", "DISALLOWED")
    assert body["result"]["acceptance_day"] == "2026-03-10"
    assert body["documents"][0]["facts"][0]["verified"] is True


@pytest.mark.parametrize("raw,expected", [("503 UNAVAILABLE model overloaded", "overloaded"),
                                          ("429 RESOURCE_EXHAUSTED quota", "rate limit"),
                                          ("Read timed out", "in time")])
def test_provider_failure_abstains_without_leaking_raw_error(monkeypatch, raw, expected):
    def failing(path, cache_dir=None):
        raise ExtractionError(f"{path.name}: Gemini call failed: {raw} secret-internal-detail")
    monkeypatch.setattr(web, "extract", failing)
    body = upload([("challan.txt", CHALLAN, "text/plain")]).json()
    assert body["status"] == "ABSTAIN" and body["decision"] is None
    assert body["reasons"][0]["code"] == "EXTRACTION_FAILED"
    assert expected in body["reasons"][0]["detail"]
    assert "secret-internal-detail" not in str(body)


@pytest.mark.parametrize("files,overrides,status", [
    ([("evil.exe", b"MZ", "application/octet-stream")], {}, 415),
    ([("fake.pdf", b"not a pdf", "application/pdf")], {}, 415),
    ([("empty.txt", b"", "text/plain")], {}, 422),
    ([("ok.txt", CHALLAN, "text/plain")], {"invoice_no": "../../etc"}, 422),
    ([("ok.txt", CHALLAN, "text/plain")], {"invoice_date": "10/03/2026"}, 422),
    ([("ok.txt", CHALLAN, "text/plain")] * 7, {}, 422),
])
def test_upload_rejects_bad_input(monkeypatch, files, overrides, status):
    monkeypatch.setattr(web, "extract", fake_extract)
    assert upload(files, **overrides).status_code == status


def test_uploaded_names_cannot_escape_the_temp_folder(monkeypatch):
    seen = []

    def spy(path, cache_dir=None):
        seen.append(path)
        return fake_extract(path)
    monkeypatch.setattr(web, "extract", spy)
    upload([("../../../../tmp/pwned.txt", CHALLAN, "text/plain")])
    assert seen and seen[0].name == "01-pwned.txt" and seen[0].parent.name == "INV-9"


def test_rate_limit(monkeypatch):
    monkeypatch.setattr(web, "extract", fake_extract)
    codes = [upload([("c.txt", CHALLAN, "text/plain")]).status_code for _ in range(web.RATE_LIMIT + 1)]
    assert codes[-1] == 429 and set(codes[:-1]) == {200}


def test_spoofed_forwarded_for_does_not_reset_the_limit(monkeypatch):
    monkeypatch.setattr(web, "extract", fake_extract)
    codes = [client.post("/api/analyze", data=FORM, files=[("files", ("c.txt", CHALLAN, "text/plain"))],
                         headers={"x-forwarded-for": f"10.0.0.{i}, 203.0.113.7"}).status_code
             for i in range(web.RATE_LIMIT + 1)]
    assert codes[-1] == 429


def test_oversized_image_is_rejected(monkeypatch):
    import io
    from PIL import Image
    monkeypatch.setattr(web, "MAX_IMAGE_PIXELS", 100)
    buffer = io.BytesIO()
    Image.new("RGB", (20, 20), "white").save(buffer, "PNG")
    assert upload([("big.png", buffer.getvalue(), "image/png")]).status_code == 413
