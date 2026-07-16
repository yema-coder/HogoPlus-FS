"""Prompt 9 — ANPR pipeline hardening: OCR-confusable normalization, Universal-Key
vision fallback, and explicit plate_status/confidence/source/reason persistence."""

from app.anpr import extract_plate, extract_plate_from_lines, normalize_plate
from app.tasks import _detect_plate_async
from tests.conftest import PHONES, login


async def _mk_incident(client, headers):
    r = await client.post(
        "/api/incidents",
        json={
            "category": "safety",
            "department_code": "PRODUCTION",
            "photo_key": "plate.jpg",
            "description": "anpr pipeline test",
            "gps_lat": 19.0754,
            "gps_lng": 72.8319,
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    return r.json()


class FakeStorage:
    def get(self, key):
        return b"fake-jpeg-bytes"


class BrokenStorage:
    def get(self, key):
        raise RuntimeError("R2 unreachable")


# ---------------- normalization / validation ----------------

def test_normalize_plate_ocr_confusables():
    # the real production failure: Rekognition read MH02FX2660 as "MHO2FX2660"
    assert normalize_plate("MHO2FX2660") == "MH02FX2660"
    assert normalize_plate("MH02FX2660") == "MH02FX2660"
    assert normalize_plate("MHO2FXZ66O") == "MH02FX2660"  # multiple confusables
    assert normalize_plate("DL8CAF5030") == "DL8CAF5030"  # 1-digit RTO
    assert normalize_plate("KA-01-AB-1234") == "KA01AB1234"  # separators stripped


def test_normalize_plate_rejects_invalid():
    assert normalize_plate("HELLO") is None
    assert normalize_plate("SPEEDLIMIT30") is None
    assert normalize_plate("XY12AB1234") is None  # XY is not an Indian state code
    assert normalize_plate("") is None


def test_extract_plate_from_lines_confidence_and_compat():
    lines = [
        {"text": "DESIGNO", "confidence": 99.0},
        {"text": "MHO2FX2660", "confidence": 64.2},
        {"text": "IND", "confidence": 90.0},
    ]
    plate, conf = extract_plate_from_lines(lines)
    assert plate == "MH02FX2660"
    assert conf == 64.2
    # exact regex hit beats coerced candidates
    lines = [
        {"text": "MHO2FXZ66O", "confidence": 99.0},
        {"text": "MH 12 AB 1234", "confidence": 55.0},
    ]
    plate, _conf = extract_plate_from_lines(lines)
    assert plate == "MH12AB1234"
    # plain-string lines still supported (back-compat helper)
    assert extract_plate(["MH 12 AB 1234"]) == "MH12AB1234"
    assert extract_plate(["JUST A WALL"]) is None


# ---------------- pipeline persistence ----------------

async def test_pipeline_stores_detected_with_coercion(client, monkeypatch):
    w = await login(client, PHONES["w_prod1"])
    inc = await _mk_incident(client, w)
    assert inc["plate_status"] == "pending"  # set at creation when photo present

    monkeypatch.setattr("app.storage.get_storage", lambda: FakeStorage())
    monkeypatch.setattr(
        "app.aws.detect_text", lambda b: [{"text": "MHO2FX2660", "confidence": 64.2}]
    )
    out = await _detect_plate_async("incident", inc["id"])
    assert out["plate_status"] == "detected"

    body = (await client.get(f"/api/incidents/{inc['id']}", headers=w)).json()
    assert body["detected_plate"] == "MH02FX2660"
    assert body["plate_status"] == "detected"
    assert body["plate_source"] == "rekognition"
    assert round(body["plate_confidence"], 1) == 64.2
    assert body["plate_reason"] is None


async def test_pipeline_llm_vision_fallback(client, monkeypatch):
    w = await login(client, PHONES["w_prod1"])
    inc = await _mk_incident(client, w)

    async def fake_llm(img):
        return "KA01AB1234", 88.0

    monkeypatch.setattr("app.storage.get_storage", lambda: FakeStorage())
    monkeypatch.setattr(
        "app.aws.detect_text", lambda b: [{"text": "SOME WALL TEXT", "confidence": 90.0}]
    )
    monkeypatch.setattr("app.anpr.llm_plate_fallback", fake_llm)
    out = await _detect_plate_async("incident", inc["id"])
    assert out["vision_calls"] == 1

    body = (await client.get(f"/api/incidents/{inc['id']}", headers=w)).json()
    assert body["detected_plate"] == "KA01AB1234"
    assert body["plate_status"] == "detected"
    assert body["plate_source"] == "llm_vision"
    assert body["plate_confidence"] == 88.0


async def test_pipeline_no_text_found(client, monkeypatch):
    w = await login(client, PHONES["w_prod1"])
    inc = await _mk_incident(client, w)

    async def no_llm(img):
        return None, None

    monkeypatch.setattr("app.storage.get_storage", lambda: FakeStorage())
    monkeypatch.setattr("app.aws.detect_text", lambda b: [])
    monkeypatch.setattr("app.anpr.llm_plate_fallback", no_llm)
    await _detect_plate_async("incident", inc["id"])

    body = (await client.get(f"/api/incidents/{inc['id']}", headers=w)).json()
    assert body["plate_status"] == "not_detected"
    assert body["plate_reason"] == "no_text_found"


async def test_pipeline_detection_failed(client, monkeypatch):
    w = await login(client, PHONES["w_prod1"])
    inc = await _mk_incident(client, w)

    monkeypatch.setattr("app.storage.get_storage", lambda: BrokenStorage())
    await _detect_plate_async("incident", inc["id"])

    body = (await client.get(f"/api/incidents/{inc['id']}", headers=w)).json()
    assert body["plate_status"] == "not_detected"
    assert body["plate_reason"] == "detection_failed"
