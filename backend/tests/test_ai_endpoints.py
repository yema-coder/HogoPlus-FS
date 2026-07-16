"""Phase 4 Part C — AI endpoints (mocked LLM/STT/Rekognition) + admin AI ops."""
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select

from app.config import settings
from app.models import FormDefinition
from tests.conftest import PHONES, login

pytestmark = pytest.mark.asyncio


def _write_file(key: str, content: bytes = b"\xff\xd8\xfffake") -> None:
    base = Path(settings.upload_dir)
    base.mkdir(parents=True, exist_ok=True)
    (base / key).write_bytes(content)


async def _auth(client, phone=PHONES["w_prod1"]):
    return await login(client, phone)


# ---------------- ANPR ----------------

async def test_anpr_vision_valid_plate(client, monkeypatch):
    _write_file("plate1.jpg")

    async def fake_vision(prompt, image):
        return {"plate": "mh 12 ab 1234", "confidence": 0.93}

    monkeypatch.setattr("app.ai_core.vision_json", fake_vision)
    headers = await _auth(client)
    r = await client.post("/api/ai/anpr", json={"photo_key": "plate1.jpg"}, headers=headers)
    assert r.status_code == 200
    data = r.json()
    assert data["plate"] == "MH12AB1234"  # normalized: uppercase, no spaces
    assert data["valid"] is True
    assert data["source"] == "vision"
    assert data["confidence"] == 0.93
    assert data["model"]


async def test_anpr_fallback_to_detect_text(client, monkeypatch):
    _write_file("plate2.jpg")

    async def fake_vision(prompt, image):
        return {"plate": "garbage!!", "confidence": 0.3}

    monkeypatch.setattr("app.ai_core.vision_json", fake_vision)
    monkeypatch.setattr(
        "app.routers.ai.detect_text",
        lambda image: [
            {"text": "SUGAR FACTORY", "confidence": 99.0},
            {"text": "MH 09 C 4321", "confidence": 96.5},
        ],
    )
    headers = await _auth(client)
    r = await client.post("/api/ai/anpr", json={"photo_key": "plate2.jpg"}, headers=headers)
    assert r.status_code == 200
    data = r.json()
    assert data["plate"] == "MH09C4321"
    assert data["source"] == "rekognition_detect_text"
    assert data["valid"] is True


async def test_anpr_nothing_found(client, monkeypatch):
    _write_file("plate3.jpg")

    async def fake_vision(prompt, image):
        return {"plate": None, "confidence": 0.0}

    monkeypatch.setattr("app.ai_core.vision_json", fake_vision)
    monkeypatch.setattr("app.routers.ai.detect_text", lambda image: [])
    headers = await _auth(client)
    r = await client.post("/api/ai/anpr", json={"photo_key": "plate3.jpg"}, headers=headers)
    assert r.status_code == 200
    data = r.json()
    assert data["plate"] is None
    assert data["valid"] is False


async def test_anpr_missing_photo_404(client):
    headers = await _auth(client)
    r = await client.post("/api/ai/anpr", json={"photo_key": "nope.jpg"}, headers=headers)
    assert r.status_code == 404


# ---------------- Gauge read ----------------

async def test_gauge_read_in_range(client, monkeypatch):
    _write_file("gauge1.jpg")

    async def fake_vision(prompt, image):
        return {"value": 72.5, "unit": "brix", "confidence": 0.88}

    monkeypatch.setattr("app.ai_core.vision_json", fake_vision)
    headers = await _auth(client)
    r = await client.post(
        "/api/ai/gauge-read",
        json={"photo_key": "gauge1.jpg", "expected_min": 0, "expected_max": 100},
        headers=headers,
    )
    assert r.status_code == 200
    data = r.json()
    assert data["value"] == 72.5
    assert data["in_range"] is True


async def test_gauge_read_out_of_range_warns(client, monkeypatch):
    _write_file("gauge2.jpg")

    async def fake_vision(prompt, image):
        return {"value": 150.0, "unit": None, "confidence": 0.9}

    monkeypatch.setattr("app.ai_core.vision_json", fake_vision)
    headers = await _auth(client)
    r = await client.post(
        "/api/ai/gauge-read",
        json={"photo_key": "gauge2.jpg", "expected_min": 0, "expected_max": 100},
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["in_range"] is False


# ---------------- Voice fill ----------------

async def test_voice_fill_maps_fields(client, db_session, monkeypatch):
    _write_file("note1.m4a", b"fake-audio")
    form = (
        await db_session.execute(
            select(FormDefinition).where(FormDefinition.code == "hourly_process_log")
        )
    ).scalar_one()

    async def fake_transcribe(audio, ext):
        return "स्टेशन पॅन, ब्रिक्स बहात्तर पूर्णांक पाच", "mr"

    async def fake_text_json(system, prompt):
        return {"fields": {"station": "PAN", "brix_value": "72.5", "unknown_key": "x", "reading_photo": "skip.jpg"}}

    monkeypatch.setattr("app.ai_core.transcribe_audio", fake_transcribe)
    monkeypatch.setattr("app.ai_core.text_json", fake_text_json)
    headers = await _auth(client)
    r = await client.post(
        "/api/ai/voice-fill",
        json={"audio_key": "note1.m4a", "form_definition_id": str(form.id)},
        headers=headers,
    )
    assert r.status_code == 200
    data = r.json()
    assert data["language"] == "mr"
    assert data["transcript"].startswith("स्टेशन")
    # select matched case-insensitively to the verbatim option, number coerced,
    # unknown + photo keys dropped
    assert data["fields"] == {"station": "pan", "brix_value": 72.5}


async def test_voice_fill_unknown_form_404(client, monkeypatch):
    _write_file("note2.m4a", b"fake-audio")
    headers = await _auth(client)
    r = await client.post(
        "/api/ai/voice-fill",
        json={"audio_key": "note2.m4a", "form_definition_id": str(uuid.uuid4())},
        headers=headers,
    )
    assert r.status_code == 404


# ---------------- SOP chat ----------------

async def test_chat_no_docs_returns_honest_fallback(client, monkeypatch):
    monkeypatch.setattr("app.embeddings.embed_query", lambda q: [0.0] * 384)
    headers = await _auth(client)  # language_pref=mr
    r = await client.post("/api/ai/chat", json={"message": "बॉयलर SOP काय आहे?"}, headers=headers)
    assert r.status_code == 200
    data = r.json()
    assert "SOP" in data["answer"]  # canned trilingual fallback
    assert data["citations"] == []
    assert data["conversation_id"]

    # follow-up in same conversation persists history
    r2 = await client.post(
        "/api/ai/chat",
        json={"message": "आणखी सांगा", "conversation_id": data["conversation_id"]},
        headers=headers,
    )
    assert r2.status_code == 200
    assert r2.json()["conversation_id"] == data["conversation_id"]


# ---------------- Admin: SOP docs, usage, backup, report ----------------

async def test_sop_doc_upload_requires_cgm(client):
    headers = await _auth(client)  # worker
    r = await client.post(
        "/api/admin/sop-docs",
        files={"file": ("sop.pdf", b"%PDF-1.4 fake", "application/pdf")},
        headers=headers,
    )
    assert r.status_code == 403


async def test_sop_doc_upload_and_list(client, monkeypatch):
    headers = await login(client, PHONES["cgm"])
    r = await client.post(
        "/api/admin/sop-docs",
        files={"file": ("boiler_sop.pdf", b"%PDF-1.4 fake pdf content", "application/pdf")},
        headers=headers,
    )
    assert r.status_code == 200
    doc = r.json()
    assert doc["title"] == "boiler_sop"
    assert doc["status"] == "pending"

    r = await client.get("/api/admin/sop-docs", headers=headers)
    assert any(d["id"] == doc["id"] for d in r.json())

    # non-pdf rejected
    r = await client.post(
        "/api/admin/sop-docs",
        files={"file": ("x.pdf", b"not a pdf", "application/pdf")},
        headers=headers,
    )
    assert r.status_code == 400

    # delete
    r = await client.delete(f"/api/admin/sop-docs/{doc['id']}", headers=headers)
    assert r.status_code == 200


async def test_ai_usage_endpoint(client):
    worker_headers = await _auth(client)
    r = await client.get("/api/admin/ai-usage", headers=worker_headers)
    assert r.status_code == 403

    r = await client.get("/api/admin/ai-usage", headers=await login(client, PHONES["cgm"]))
    assert r.status_code == 200
    data = r.json()
    assert "counts" in data and "rekognition_failures" in data


async def test_backup_now_permissions_and_local_skip(client):
    worker_headers = await _auth(client)
    r = await client.post("/api/admin/backup-now", headers=worker_headers)
    assert r.status_code == 403

    r = await client.post("/api/admin/backup-now", headers=await login(client, PHONES["cgm"]))
    assert r.status_code == 200
    assert r.json() == {"skipped": True, "reason": "local storage mode"}  # tests run FILE_STORAGE_MODE=local


async def test_incident_out_includes_severity_reason(client, db_session):
    _write_file("inc_photo.jpg")
    headers = await _auth(client)
    r = await client.post(
        "/api/incidents",
        json={
            "department_code": "PRODUCTION",
            "category": "machine_breakdown",
            "photo_key": "inc_photo.jpg",
            "severity": "normal",
            "description": "test",
        },
        headers=headers,
    )
    assert r.status_code in (200, 201)
    assert "severity_reason" in r.json()
