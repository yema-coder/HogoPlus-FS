"""Live smoke test for v1.0.21 P0 — POST /ai/tts (with server hash cache)
and POST /ai/voice-describe (Whisper STT). Uses the DEMO bubble worker
+919000000009 (OTP 123456) against the public preview backend.

Runs against LIVE Emergent LLM key — keep the payloads modest.
"""
import os
import time
import uuid
import wave
import struct
import io
import pytest
import requests

BASE = "https://hogo-backend-phase1.preview.emergentagent.com"

DEMO_WORKER = "+919000000009"


def _login(phone: str) -> str:
    r = requests.post(f"{BASE}/api/auth/send-otp", json={"phone": phone}, timeout=15)
    assert r.status_code in (200, 202, 429), r.text
    r2 = requests.post(
        f"{BASE}/api/auth/verify-otp",
        json={"phone": phone, "otp": "123456"},
        timeout=15,
    )
    assert r2.status_code == 200, f"login failed {r2.status_code} {r2.text}"
    data = r2.json()
    return data["access"] if "access" in data else data["access_token"]


@pytest.fixture(scope="module")
def worker_token():
    return _login(DEMO_WORKER)


@pytest.fixture(scope="module")
def headers(worker_token):
    return {"Authorization": f"Bearer {worker_token}"}


def _make_silent_wav_bytes(duration_s: float = 1.0, sr: int = 16000) -> bytes:
    """Generate a small silent WAV in-memory (for the STT smoke test)."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(b"\x00\x00" * int(sr * duration_s))
    return buf.getvalue()


# ---------------- TTS ----------------

UNIQUE_MARATHI = f"चाचणी संदेश {uuid.uuid4().hex[:8]} — पंप गळती."


def test_tts_generate_then_cached(headers):
    r1 = requests.post(
        f"{BASE}/api/ai/tts", headers=headers, json={"text": UNIQUE_MARATHI}, timeout=60
    )
    assert r1.status_code == 200, r1.text
    d1 = r1.json()
    assert d1["cached"] is False
    assert d1["key"].endswith(".mp3")
    assert d1["url"] == f"/api/files/{d1['key']}"

    # second call → cached with same key
    r2 = requests.post(
        f"{BASE}/api/ai/tts", headers=headers, json={"text": UNIQUE_MARATHI}, timeout=30
    )
    assert r2.status_code == 200
    d2 = r2.json()
    assert d2["cached"] is True
    assert d2["key"] == d1["key"]

    # Follow redirect on the audio URL — must reach a playable mp3
    r3 = requests.get(f"{BASE}/api/files/{d1['key']}", allow_redirects=True, timeout=30)
    assert r3.status_code == 200, f"{r3.status_code}"
    # First 3 bytes could be "ID3" tag OR mp3 frame sync
    prefix = r3.content[:4]
    assert prefix[:3] == b"ID3" or (prefix[0] == 0xFF and (prefix[1] & 0xE0) == 0xE0), (
        f"unexpected mp3 prefix {prefix!r}"
    )
    assert len(r3.content) > 1000, "mp3 too small"


def test_tts_empty_text_422(headers):
    r = requests.post(f"{BASE}/api/ai/tts", headers=headers, json={"text": ""}, timeout=15)
    assert r.status_code == 422, r.text


def test_tts_601_char_text_422(headers):
    r = requests.post(
        f"{BASE}/api/ai/tts", headers=headers, json={"text": "क" * 601}, timeout=15
    )
    assert r.status_code == 422, r.text


def test_tts_no_auth_401():
    r = requests.post(f"{BASE}/api/ai/tts", json={"text": "hello"}, timeout=15)
    assert r.status_code == 401, r.text


# ---------------- voice-describe ----------------


def test_voice_describe_no_auth_401():
    r = requests.post(
        f"{BASE}/api/ai/voice-describe", json={"audio_key": "nope.m4a"}, timeout=15
    )
    assert r.status_code == 401, r.text


def test_voice_describe_missing_audio_404(headers):
    r = requests.post(
        f"{BASE}/api/ai/voice-describe",
        headers=headers,
        json={"audio_key": f"missing-{uuid.uuid4().hex}.m4a"},
        timeout=15,
    )
    assert r.status_code == 404, r.text


def test_voice_describe_live_silence_returns_200(headers):
    """Upload a REAL 1s silent MP3 (ffmpeg lavfi anullsrc) → LIVE Whisper.
    Even silence should return 200 with an empty-ish transcript (per spec)."""
    import shutil
    import subprocess
    from pathlib import Path

    if not Path("/tmp/silence1s.mp3").exists():
        if not shutil.which("ffmpeg"):
            pytest.skip("ffmpeg unavailable (pod recycle) — live silence smoke skipped")
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono",
             "-t", "1", "-q:a", "9", "/tmp/silence1s.mp3"],
            capture_output=True, check=True,
        )
    with open("/tmp/silence1s.mp3", "rb") as f:
        mp3_bytes = f.read()
    files = {"file": ("silence.mp3", mp3_bytes, "audio/mpeg")}
    up = requests.post(
        f"{BASE}/api/files/upload", headers=headers, files=files, timeout=30
    )
    assert up.status_code == 200, up.text
    key = up.json()["key"]
    r = requests.post(
        f"{BASE}/api/ai/voice-describe",
        headers=headers,
        json={"audio_key": key},
        timeout=90,
    )
    # LIVE Whisper — must succeed (200). Transcript may be empty for silence.
    assert r.status_code == 200, f"{r.status_code} {r.text}"
    body = r.json()
    assert "transcript" in body
    assert "description" in body
    assert "language" in body
