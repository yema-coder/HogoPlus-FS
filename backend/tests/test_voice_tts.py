"""v1.0.21 P0 — Voice-first reporting (POST /ai/voice-describe) + Read-aloud TTS
(POST /ai/tts).

Coverage demanded by the owner: success paths, per-user daily caps (trilingual
429s), cache behaviour (same text NEVER synthesized twice; cached hits bypass
the cap), failure fallbacks (STT 502, LLM falls back to raw transcript),
auth boundaries, and the server-side description fill for offline-queued voice
incidents. Runs against the live local Postgres + Redis test infra.
"""
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select

from app import ai_core
from app.config import settings
from app.redis_client import redis_client
from tests.conftest import PHONES, login

pytestmark = pytest.mark.asyncio


def _write_file(key: str, content: bytes = b"\x00\x00\x00\x18ftypM4A fake-audio") -> None:
    base = Path(settings.upload_dir)
    base.mkdir(parents=True, exist_ok=True)
    (base / key).write_bytes(content)


@pytest.fixture(autouse=True)
async def _clean_ai_keys():
    """Per-user daily caps + tts hash cache persist in redis — isolate tests."""
    async for key in redis_client.scan_iter("ai:usercap:*"):
        await redis_client.delete(key)
    async for key in redis_client.scan_iter("tts:key:*"):
        await redis_client.delete(key)
    yield


# ---------------- voice-describe (voice-first reporting) ----------------

async def test_voice_describe_writes_description(client, monkeypatch):
    _write_file("vd1.m4a")

    async def fake_stt(audio, ext):
        assert ext == "m4a"
        return "पंप नंबर दोन जवळ पाणी गळत आहे बरं का", "mr"

    async def fake_text_json(system, prompt):
        assert "Spoken report (Marathi)" in prompt
        return {"description": "पंप क्रमांक २ जवळ पाण्याची गळती आहे."}

    monkeypatch.setattr(ai_core, "transcribe_audio", fake_stt)
    monkeypatch.setattr(ai_core, "text_json", fake_text_json)
    headers = await login(client, PHONES["w_prod1"])
    r = await client.post("/api/ai/voice-describe", json={"audio_key": "vd1.m4a"}, headers=headers)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["transcript"] == "पंप नंबर दोन जवळ पाणी गळत आहे बरं का"
    assert data["description"] == "पंप क्रमांक २ जवळ पाण्याची गळती आहे."
    assert data["language"] == "mr"


async def test_voice_describe_llm_failure_falls_back_to_transcript(client, monkeypatch):
    _write_file("vd2.m4a")

    async def fake_stt(audio, ext):
        return "बॉयलर के पास धुआँ है", "hi"

    async def broken_llm(system, prompt):
        raise RuntimeError("llm down")

    monkeypatch.setattr(ai_core, "transcribe_audio", fake_stt)
    monkeypatch.setattr(ai_core, "text_json", broken_llm)
    headers = await login(client, PHONES["w_prod1"])
    r = await client.post("/api/ai/voice-describe", json={"audio_key": "vd2.m4a"}, headers=headers)
    assert r.status_code == 200
    # never a dead end: raw transcript is still returned as the description
    assert r.json()["description"] == "बॉयलर के पास धुआँ है"


async def test_voice_describe_stt_failure_502(client, monkeypatch):
    _write_file("vd3.m4a")

    async def broken_stt(audio, ext):
        raise RuntimeError("whisper down")

    monkeypatch.setattr(ai_core, "transcribe_audio", broken_stt)
    headers = await login(client, PHONES["w_prod1"])
    r = await client.post("/api/ai/voice-describe", json={"audio_key": "vd3.m4a"}, headers=headers)
    assert r.status_code == 502


async def test_voice_describe_daily_cap_trilingual_429(client, monkeypatch):
    _write_file("vd4.m4a")

    async def fake_stt(audio, ext):
        return "test", "mr"

    async def fake_text_json(system, prompt):
        return {"description": "test description"}

    monkeypatch.setattr(ai_core, "transcribe_audio", fake_stt)
    monkeypatch.setattr(ai_core, "text_json", fake_text_json)
    monkeypatch.setattr(settings, "voice_describe_daily_cap", 1)
    headers = await login(client, PHONES["w_prod2"])
    r1 = await client.post("/api/ai/voice-describe", json={"audio_key": "vd4.m4a"}, headers=headers)
    assert r1.status_code == 200
    r2 = await client.post("/api/ai/voice-describe", json={"audio_key": "vd4.m4a"}, headers=headers)
    assert r2.status_code == 429
    detail = r2.json()["detail"]
    assert detail["code"] == "voice_cap_reached"
    assert all(lang in detail for lang in ("en", "hi", "mr"))


async def test_voice_describe_cap_is_per_user(client, monkeypatch):
    """Another employee is NOT blocked by the first user's exhausted cap."""
    _write_file("vd5.m4a")

    async def fake_stt(audio, ext):
        return "ok", "mr"

    async def fake_text_json(system, prompt):
        return {"description": "ok"}

    monkeypatch.setattr(ai_core, "transcribe_audio", fake_stt)
    monkeypatch.setattr(ai_core, "text_json", fake_text_json)
    monkeypatch.setattr(settings, "voice_describe_daily_cap", 1)
    h1 = await login(client, PHONES["w_prod2"])
    h2 = await login(client, PHONES["w_prod3"])
    assert (await client.post("/api/ai/voice-describe", json={"audio_key": "vd5.m4a"}, headers=h1)).status_code == 200
    assert (await client.post("/api/ai/voice-describe", json={"audio_key": "vd5.m4a"}, headers=h1)).status_code == 429
    assert (await client.post("/api/ai/voice-describe", json={"audio_key": "vd5.m4a"}, headers=h2)).status_code == 200


async def test_voice_describe_missing_audio_404(client):
    headers = await login(client, PHONES["w_prod1"])
    r = await client.post(
        "/api/ai/voice-describe", json={"audio_key": f"missing-{uuid.uuid4().hex}.m4a"}, headers=headers
    )
    assert r.status_code == 404


async def test_voice_describe_requires_auth(client):
    r = await client.post("/api/ai/voice-describe", json={"audio_key": "vd1.m4a"})
    assert r.status_code == 401


# ---------------- TTS (read-aloud) ----------------

MARATHI_TEXT = "पंप क्रमांक दोन जवळ पाण्याची गळती आहे. त्वरित तपासणी करा."
FAKE_MP3 = b"ID3" + b"\x00" * 64


async def test_tts_generates_and_serves_cached_second_call(client, monkeypatch):
    calls = {"n": 0}

    async def fake_synth(text):
        calls["n"] += 1
        assert text == MARATHI_TEXT
        return FAKE_MP3

    monkeypatch.setattr(ai_core, "synthesize_speech", fake_synth)
    headers = await login(client, PHONES["w_prod1"])

    r1 = await client.post("/api/ai/tts", json={"text": MARATHI_TEXT}, headers=headers)
    assert r1.status_code == 200, r1.text
    d1 = r1.json()
    assert d1["cached"] is False
    assert d1["key"].endswith(".mp3")
    assert d1["url"] == f"/api/files/{d1['key']}"
    # audio actually stored and playable
    assert (Path(settings.upload_dir) / d1["key"]).read_bytes() == FAKE_MP3

    r2 = await client.post("/api/ai/tts", json={"text": MARATHI_TEXT}, headers=headers)
    assert r2.status_code == 200
    d2 = r2.json()
    assert d2["cached"] is True
    assert d2["key"] == d1["key"]
    assert calls["n"] == 1  # the same sentence is NEVER synthesized twice


async def test_tts_cache_hit_bypasses_daily_cap(client, monkeypatch):
    async def fake_synth(text):
        return FAKE_MP3

    monkeypatch.setattr(ai_core, "synthesize_speech", fake_synth)
    monkeypatch.setattr(settings, "tts_daily_cap", 1)
    headers = await login(client, PHONES["w_prod2"])

    r1 = await client.post("/api/ai/tts", json={"text": "एक"}, headers=headers)
    assert r1.status_code == 200
    # cap exhausted → NEW text is rejected...
    r2 = await client.post("/api/ai/tts", json={"text": "दोन"}, headers=headers)
    assert r2.status_code == 429
    detail = r2.json()["detail"]
    assert detail["code"] == "tts_cap_reached"
    assert all(lang in detail for lang in ("en", "hi", "mr"))
    # ...but already-generated audio still plays (cached hits are free)
    r3 = await client.post("/api/ai/tts", json={"text": "एक"}, headers=headers)
    assert r3.status_code == 200
    assert r3.json()["cached"] is True


async def test_tts_synth_failure_502(client, monkeypatch):
    async def broken_synth(text):
        raise RuntimeError("tts down")

    monkeypatch.setattr(ai_core, "synthesize_speech", broken_synth)
    headers = await login(client, PHONES["w_prod1"])
    r = await client.post("/api/ai/tts", json={"text": f"unique {uuid.uuid4().hex}"}, headers=headers)
    assert r.status_code == 502


async def test_tts_validation(client):
    headers = await login(client, PHONES["w_prod1"])
    r = await client.post("/api/ai/tts", json={"text": ""}, headers=headers)
    assert r.status_code == 422
    r = await client.post("/api/ai/tts", json={"text": "क" * 601}, headers=headers)
    assert r.status_code == 422
    r = await client.post("/api/ai/tts", json={"text": "   "}, headers=headers)
    assert r.status_code == 422


async def test_tts_requires_auth(client):
    r = await client.post("/api/ai/tts", json={"text": "hello"})
    assert r.status_code == 401


# ---------------- server-side description fill (offline voice path) ----------------

async def _create_voice_incident(client, headers, description=None):
    payload = {
        "category": "other", "department_code": "PRODUCTION", "photo_key": "p.jpg",
        "voice_note_key": "vn-offline.m4a", "gps_lat": 19.0, "gps_lng": 74.7,
        "description": description,
    }
    r = await client.post("/api/incidents", json=payload, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _patch_incident_ai(monkeypatch, written_description):
    async def fake_stt(audio, ext):
        return "मशीन मधून मोठा आवाज येतो आहे", "mr"

    async def fake_text_json(system, prompt):
        if "Spoken report" in prompt:
            return {"description": written_description}
        return {
            "category": "machine_breakdown", "department_code": "ENGINEERING",
            "severity": "high", "confidence": 0.85,
            "reason": "loud machine noise", "reason_mr": "मशीनचा मोठा आवाज",
        }

    class FakeStorage:
        def get(self, key):
            if key.endswith(".m4a"):
                return b"fake-audio"
            raise FileNotFoundError(key)  # photo missing → text classification path

    import app.ai_core as ai_core_mod

    monkeypatch.setattr(ai_core_mod, "transcribe_audio", fake_stt)
    monkeypatch.setattr(ai_core_mod, "text_json", fake_text_json)
    monkeypatch.setattr(ai_core_mod, "vision_json", fake_text_json, raising=False)
    monkeypatch.setattr("app.storage.get_storage", lambda: FakeStorage())


async def test_offline_voice_incident_gets_server_written_description(
    client, db_session, monkeypatch
):
    """An incident queued offline arrives with a voice note and NO description —
    the server transcribes and writes the description (report never lost)."""
    from app.models import IncidentTimeline
    from app.tasks import _classify_incident_async

    w = await login(client, PHONES["w_prod1"])
    inc = await _create_voice_incident(client, w, description=None)
    _patch_incident_ai(monkeypatch, "मशीनमधून मोठा आवाज येत आहे — तपासणी आवश्यक.")

    await _classify_incident_async(inc["id"])

    r = await client.get(f"/api/incidents/{inc['id']}", headers=w)
    body = r.json()
    assert body["description"] == "मशीनमधून मोठा आवाज येत आहे — तपासणी आवश्यक."
    rows = (
        await db_session.execute(
            select(IncidentTimeline).where(IncidentTimeline.incident_id == uuid.UUID(inc["id"]))
        )
    ).scalars().all()
    voice_events = [t for t in rows if t.event == "voice_transcribed"]
    assert len(voice_events) == 1
    assert voice_events[0].detail_json["language"] == "mr"


async def test_typed_description_never_overwritten_by_voice(client, db_session, monkeypatch):
    from app.models import IncidentTimeline
    from app.tasks import _classify_incident_async

    w = await login(client, PHONES["w_prod1"])
    inc = await _create_voice_incident(client, w, description="typed by the worker")
    _patch_incident_ai(monkeypatch, "SHOULD NOT APPEAR")

    await _classify_incident_async(inc["id"])

    r = await client.get(f"/api/incidents/{inc['id']}", headers=w)
    assert r.json()["description"] == "typed by the worker"
    rows = (
        await db_session.execute(
            select(IncidentTimeline).where(IncidentTimeline.incident_id == uuid.UUID(inc["id"]))
        )
    ).scalars().all()
    assert not [t for t in rows if t.event == "voice_transcribed"]
