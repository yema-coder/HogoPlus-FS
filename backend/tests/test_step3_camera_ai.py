"""Step 3 — on-device distance persistence + backend face/plate analysis.

The ONNX models are NOT loaded in tests: ``app.vision_local.analyze_image`` is
monkeypatched with a canned result so the pipeline wiring (DB rows, detected_plate
sync, role-scoped endpoints, editable plates, feature flags) is exercised offline.
"""
import pytest
from sqlalchemy import text

from tests.conftest import PHONES, login


async def _create_incident(client, headers, dept="PRODUCTION", **extra):
    body = {"category": "machine_breakdown", "department_code": dept, "photo_key": "inc.jpg",
            "gps_lat": 19.0, "gps_lng": 74.7, "description": "t"}
    body.update(extra)
    r = await client.post("/api/incidents", json=body, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


# ---- distance persistence ---------------------------------------------------

async def test_distance_persisted_and_returned(client):
    headers = await login(client, PHONES["w_prod1"])
    inc = await _create_incident(
        client, headers,
        distance_m=6.4, distance_method="lidar", distance_confidence="high",
        distance_uncertainty_m=0.3,
    )
    assert inc["distance_m"] == 6.4
    assert inc["distance_method"] == "lidar"
    assert inc["distance_confidence"] == "high"
    assert inc["distance_uncertainty_m"] == 0.3
    # survives on the detail read
    r = await client.get(f"/api/incidents/{inc['id']}", headers=headers)
    assert r.json()["distance_m"] == 6.4


async def test_invalid_distance_method_dropped_not_rejected(client):
    headers = await login(client, PHONES["w_prod1"])
    # garbage method must NOT block the incident — distance is simply dropped
    inc = await _create_incident(
        client, headers, distance_m=5.0, distance_method="telepathy", distance_confidence="meh",
    )
    assert inc["distance_m"] is None
    assert inc["distance_method"] is None


async def test_distance_none_method_ignored(client):
    headers = await login(client, PHONES["w_prod1"])
    inc = await _create_incident(client, headers, distance_m=5.0, distance_method="none")
    assert inc["distance_m"] is None


# ---- analysis endpoint ------------------------------------------------------

async def test_analysis_empty_until_processed(client):
    headers = await login(client, PHONES["w_prod1"])
    inc = await _create_incident(client, headers, distance_m=3.2, distance_method="depth")
    r = await client.get(f"/api/incidents/{inc['id']}/analysis", headers=headers)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["photos"] == []
    assert data["pending"] is True  # has a photo_key, not analysed yet
    assert data["distance"]["distance_m"] == 3.2


async def test_analysis_not_visible_to_other_worker(client):
    owner = await login(client, PHONES["w_prod1"])
    inc = await _create_incident(client, owner)
    other = await login(client, PHONES["w_eng"])  # different dept worker
    r = await client.get(f"/api/incidents/{inc['id']}/analysis", headers=other)
    assert r.status_code in (403, 404)


@pytest.fixture
def _fake_vision(monkeypatch):
    from app import vision_local

    def fake_analyze(img_bytes, *, do_faces=True, do_plates=True):
        return {
            "ok": True,
            "faces": [{"x": 0.4, "y": 0.3, "w": 0.2, "h": 0.3, "score": 0.9}] if do_faces else None,
            "plates": (
                [{"x": 0.1, "y": 0.7, "w": 0.4, "h": 0.15, "text": "MH12AB1234",
                  "det_confidence": 0.8, "ocr_confidence": 0.97, "region": "IN"}]
                if do_plates else None
            ),
        }

    monkeypatch.setattr(vision_local, "analyze_image", fake_analyze)
    monkeypatch.setattr(vision_local, "release_models", lambda: None)
    return fake_analyze


async def test_analysis_pipeline_writes_rows_and_sets_plate(client, db_session, _fake_vision):
    from app.storage import get_storage
    from app.tasks import _analyze_photos_async

    headers = await login(client, PHONES["w_prod1"])
    key = await get_storage().save(b"\xff\xd8\xff\xe0 jpeg-ish bytes", "jpg")
    inc = await _create_incident(client, headers, photo_key=key)

    res = await _analyze_photos_async("incident", inc["id"])
    assert res["found_plate"] is True
    assert res["faces"] == 1 and res["plates"] == 1

    r = await client.get(f"/api/incidents/{inc['id']}/analysis", headers=headers)
    data = r.json()
    assert data["pending"] is False
    assert data["face_count"] == 1 and data["plate_count"] == 1
    assert data["detected_plate"] == "MH12AB1234"
    photo = data["photos"][0]
    assert photo["status"] == "done"
    assert photo["faces"][0]["score"] == 0.9
    assert photo["plates"][0]["text"] == "MH12AB1234"

    # the incident row itself now carries the plate from the local reader
    r2 = await client.get(f"/api/incidents/{inc['id']}", headers=headers)
    assert r2.json()["detected_plate"] == "MH12AB1234"
    assert r2.json()["plate_source"] == "local_onnx"


async def test_analysis_idempotent(client, _fake_vision):
    from app.storage import get_storage
    from app.tasks import _analyze_photos_async

    headers = await login(client, PHONES["w_prod1"])
    key = await get_storage().save(b"x", "jpg")
    inc = await _create_incident(client, headers, photo_key=key)
    await _analyze_photos_async("incident", inc["id"])
    res2 = await _analyze_photos_async("incident", inc["id"])  # re-run: nothing new analysed
    assert res2["analyzed"] == 0
    # still exactly one plate row (no duplicates)
    r = await client.get(f"/api/incidents/{inc['id']}/analysis", headers=headers)
    assert r.json()["plate_count"] == 1


# ---- editable plates --------------------------------------------------------

async def _plate_id(client, headers, inc_id):
    r = await client.get(f"/api/incidents/{inc_id}/analysis", headers=headers)
    return r.json()["photos"][0]["plates"][0]["id"]


async def test_manager_can_edit_plate_worker_cannot(client, _fake_vision):
    from app.storage import get_storage
    from app.tasks import _analyze_photos_async

    worker = await login(client, PHONES["w_prod1"])
    key = await get_storage().save(b"x", "jpg")
    inc = await _create_incident(client, worker, photo_key=key)
    await _analyze_photos_async("incident", inc["id"])
    pid = await _plate_id(client, worker, inc["id"])

    # reporter (worker) cannot edit
    r = await client.patch(
        f"/api/incidents/{inc['id']}/plates/{pid}", json={"text": "hack"}, headers=worker
    )
    assert r.status_code == 403

    # dept manager can — value is normalised + becomes authoritative on the incident
    mgr = await login(client, PHONES["prod_mgr"])
    r = await client.patch(
        f"/api/incidents/{inc['id']}/plates/{pid}", json={"text": "mh14gh7777"}, headers=mgr
    )
    assert r.status_code == 200, r.text
    assert r.json()["text"] == "MH14GH7777"
    assert r.json()["edited"] is True

    r2 = await client.get(f"/api/incidents/{inc['id']}", headers=mgr)
    assert r2.json()["detected_plate"] == "MH14GH7777"
    assert r2.json()["plate_source"] == "manual"


async def test_edit_plate_empty_text_422(client, _fake_vision):
    from app.storage import get_storage
    from app.tasks import _analyze_photos_async

    worker = await login(client, PHONES["w_prod1"])
    key = await get_storage().save(b"x", "jpg")
    inc = await _create_incident(client, worker, photo_key=key)
    await _analyze_photos_async("incident", inc["id"])
    pid = await _plate_id(client, worker, inc["id"])
    mgr = await login(client, PHONES["prod_mgr"])
    r = await client.patch(
        f"/api/incidents/{inc['id']}/plates/{pid}", json={"text": "   "}, headers=mgr
    )
    assert r.status_code == 422


# ---- feature flags ----------------------------------------------------------

async def test_settings_expose_camera_flags(client):
    cgm = await login(client, PHONES["cgm"])
    r = await client.get("/api/admin/settings", headers=cgm)
    assert r.status_code == 200
    body = r.json()
    for k in ("ar_distance_enabled", "face_detection_enabled", "plate_detection_enabled"):
        assert k in body and body[k] is True


async def test_plate_flag_off_skips_plate_detection(client, db_session, _fake_vision):
    from app.storage import get_storage
    from app.tasks import _analyze_photos_async

    cgm = await login(client, PHONES["cgm"])
    await client.patch("/api/admin/settings", json={"plate_detection_enabled": False}, headers=cgm)
    try:
        worker = await login(client, PHONES["w_prod1"])
        key = await get_storage().save(b"x", "jpg")
        inc = await _create_incident(client, worker, photo_key=key)
        res = await _analyze_photos_async("incident", inc["id"])
        assert res["found_plate"] is False
        r = await client.get(f"/api/incidents/{inc['id']}/analysis", headers=worker)
        data = r.json()
        assert data["plate_count"] == 0  # plates skipped
        assert data["face_count"] == 1  # faces still ran
    finally:
        await client.patch("/api/admin/settings", json={"plate_detection_enabled": True}, headers=cgm)
