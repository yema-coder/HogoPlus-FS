"""UX pack tests: AI routing suggestion + confirm/timeout, resolution photo,
punch-out reminder (mocked clock) and opportunistic ANPR (mocked Rekognition)."""
from datetime import timedelta

from sqlalchemy import text

from app import tasks as tasks_mod
from app.shift_logic import now_ist
from app.tasks import (
    _ai_timeout_sweep_async,
    _classify_incident_async,
    _detect_plate_async,
    _punchout_reminder_async,
    extract_plate,
)
from tests.conftest import PHONES, login


async def _create_incident(client, headers, **overrides):
    payload = {
        "category": "other", "department_code": "PRODUCTION", "photo_key": "p.jpg",
        "gps_lat": 19.0, "gps_lng": 74.7, "description": "sparks near the panel",
    }
    payload.update(overrides)
    r = await client.post("/api/incidents", json=payload, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


async def test_ai_classifier_stores_suggestion(client, db_session, monkeypatch):
    w = await login(client, PHONES["w_prod1"])
    inc = await _create_incident(client, w)

    async def fake_text_json(system, prompt):
        assert "sparks near the panel" in prompt
        return {"category": "electrical", "department_code": "ENGINEERING",
                "severity": "high", "confidence": 0.91, "reason": "sparks near panel"}

    import app.ai_core as ai_core
    monkeypatch.setattr(ai_core, "text_json", fake_text_json)
    monkeypatch.setattr(ai_core, "vision_json", fake_text_json, raising=False)

    class FakeStorage:
        def get(self, key):
            raise FileNotFoundError(key)  # force the text path

    monkeypatch.setattr("app.storage.get_storage", lambda: FakeStorage())
    out = await _classify_incident_async(inc["id"])
    assert out["category"] == "electrical" and out["department_code"] == "ENGINEERING"

    r = await client.get(f"/api/incidents/{inc['id']}", headers=w)
    body = r.json()
    assert body["ai_suggested_category"] == "electrical"
    assert body["ai_suggested_department"] == "ENGINEERING"
    assert body["ai_suggested_severity"] == "high"
    assert body["ai_confirmed_by"] is None  # not routed until confirmed


async def test_worker_confirms_ai_suggestion(client, db_session):
    w = await login(client, PHONES["w_prod1"])
    inc = await _create_incident(client, w)
    await db_session.execute(
        text("UPDATE incidents SET ai_suggested_category='electrical', "
             "ai_suggested_department='ENGINEERING', ai_suggested_severity='high', "
             "ai_suggested_at=now() WHERE id=:i"), {"i": inc["id"]})
    await db_session.commit()
    r = await client.post(f"/api/incidents/{inc['id']}/confirm-routing", json={}, headers=w)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["category"] == "electrical"
    assert body["department_code"] == "ENGINEERING"
    assert body["ai_confirmed_by"] == "worker"
    # second confirm is rejected
    r = await client.post(f"/api/incidents/{inc['id']}/confirm-routing", json={}, headers=w)
    assert r.status_code == 409


async def test_worker_changes_routing(client, db_session):
    w = await login(client, PHONES["w_prod1"])
    inc = await _create_incident(client, w)
    await db_session.execute(
        text("UPDATE incidents SET ai_suggested_category='electrical', "
             "ai_suggested_department='ENGINEERING', ai_suggested_severity='normal', "
             "ai_suggested_at=now() WHERE id=:i"), {"i": inc["id"]})
    await db_session.commit()
    r = await client.post(
        f"/api/incidents/{inc['id']}/confirm-routing",
        json={"category": "machine_breakdown", "department_code": "PRODUCTION"},
        headers=w,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["category"] == "machine_breakdown"
    assert body["department_code"] == "PRODUCTION"
    assert body["ai_confirmed_by"] == "worker_changed"


async def test_ai_timeout_auto_applies(client, db_session):
    w = await login(client, PHONES["w_prod1"])
    inc = await _create_incident(client, w)
    old = now_ist() - timedelta(minutes=11)
    await db_session.execute(
        text("UPDATE incidents SET ai_suggested_category='fire', "
             "ai_suggested_department='SECURITY', ai_suggested_severity='critical', "
             "ai_suggested_at=:t WHERE id=:i"), {"t": old, "i": inc["id"]})
    await db_session.commit()
    out = await _ai_timeout_sweep_async()
    assert out["applied"] >= 1
    r = await client.get(f"/api/incidents/{inc['id']}", headers=w)
    body = r.json()
    assert body["ai_confirmed_by"] == "ai_timeout"
    assert body["category"] == "fire" and body["department_code"] == "SECURITY"
    # timeline records the routing
    routed = (
        await db_session.execute(
            text("SELECT COUNT(*) FROM incident_timeline WHERE incident_id=:i AND event='routed'"),
            {"i": inc["id"]})
    ).scalar()
    assert routed == 1


async def test_punchout_reminder_once_per_day(client, db_session):
    w = await login(client, PHONES["w_att1"])
    me = await client.get("/api/auth/me", headers=w)
    emp_id = me.json()["id"]
    today = now_ist().date()
    await db_session.execute(
        text("INSERT INTO attendance (id, employee_id, date, punch_in_at, verification_level, "
             "is_late, gps_verified, selfie_key) "
             "VALUES (gen_random_uuid(), :e, :d, now(), 'verified', false, true, 's.jpg') "
             "ON CONFLICT DO NOTHING"), {"e": emp_id, "d": today})
    await db_session.commit()
    fake_now = now_ist().replace(hour=23, minute=45)  # long after any shift end
    out1 = await _punchout_reminder_async(now=fake_now)
    assert out1["sent"] >= 1
    n = (
        await db_session.execute(
            text("SELECT COUNT(*) FROM notifications WHERE recipient_id=:e AND type='punchout_reminder'"),
            {"e": emp_id})
    ).scalar()
    assert n == 1
    out2 = await _punchout_reminder_async(now=fake_now)  # redis guard → no repeat
    n2 = (
        await db_session.execute(
            text("SELECT COUNT(*) FROM notifications WHERE recipient_id=:e AND type='punchout_reminder'"),
            {"e": emp_id})
    ).scalar()
    assert n2 == 1


def test_extract_plate_regex():
    assert extract_plate(["MH 12 AB 1234"]) == "MH12AB1234"
    assert extract_plate(["truck near gate", "MH12-AB-1234 parked"]) == "MH12AB1234"
    assert extract_plate(["no vehicles here", "SPEED LIMIT 30"]) is None


async def test_anpr_plate_stored_and_silent(client, db_session, monkeypatch):
    w = await login(client, PHONES["w_prod1"])
    inc = await _create_incident(client, w)

    class FakeStorage:
        def get(self, key):
            return b"fakejpegbytes"

    monkeypatch.setattr("app.storage.get_storage", lambda: FakeStorage())
    monkeypatch.setattr("app.aws.detect_text", lambda b: ["MH 12 AB 1234", "TATA"])
    out = await _detect_plate_async("incident", inc["id"])
    assert out["plates"] == ["MH12AB1234"]
    r = await client.get(f"/api/incidents/{inc['id']}", headers=w)
    assert r.json()["detected_plate"] == "MH12AB1234"

    # no plate → nothing stored, no error
    inc2 = await _create_incident(client, w)
    monkeypatch.setattr("app.aws.detect_text", lambda b: ["JUST A WALL"])
    out = await _detect_plate_async("incident", inc2["id"])
    assert out["plates"] == []
    r = await client.get(f"/api/incidents/{inc2['id']}", headers=w)
    assert r.json()["detected_plate"] is None


def test_selfies_excluded_from_anpr():
    # attendance (selfie) and face-verification paths never dispatch plate detection
    for path in ("app/routers/attendance.py", "app/face_verification.py"):
        try:
            src = open(path).read()
        except FileNotFoundError:
            continue
        assert "detect_plate" not in src
