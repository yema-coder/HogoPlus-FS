"""Step 5 — plate-scale cross-check + calibration."""
import pytest

from app import plate_scale
from tests.conftest import PHONES, login


def test_estimate_and_consistency():
    # k=1.2, 0.5m plate, 15% of frame → ~4.0m
    out = plate_scale.compute_plate_scale(
        enabled=True, k=1.2, ref_width_m=0.5, plate_w_frac=0.15, ar_distance_m=4.2
    )
    assert out["est_distance_m"] == 4.0
    assert out["consistent"] is True and out["delta_pct"] < 10
    # a big mismatch flags inconsistent
    out2 = plate_scale.compute_plate_scale(
        enabled=True, k=1.2, ref_width_m=0.5, plate_w_frac=0.5, ar_distance_m=4.2
    )
    assert out2["consistent"] is False


def test_disabled_or_no_plate_returns_none():
    assert plate_scale.compute_plate_scale(enabled=False, k=1.2, ref_width_m=0.5, plate_w_frac=0.1, ar_distance_m=4.0) is None
    assert plate_scale.compute_plate_scale(enabled=True, k=1.2, ref_width_m=0.5, plate_w_frac=None, ar_distance_m=4.0) is None


def test_calibrate_k_roundtrip():
    k = plate_scale.calibrate_k(ar_distance_m=4.2, plate_w_frac=0.15, ref_width_m=0.5)
    assert k == 1.26
    # feeding k back reproduces ~the distance
    assert plate_scale.estimate_distance(k, 0.5, 0.15) == pytest.approx(4.2, abs=0.05)


@pytest.fixture
def _fake_vision(monkeypatch):
    from app import vision_local

    def fake_analyze(img_bytes, *, do_faces=True, do_plates=True):
        return {
            "ok": True,
            "faces": [] if do_faces else None,
            "plates": (
                [{"x": 0.3, "y": 0.6, "w": 0.15, "h": 0.08, "text": "MH12AB1234",
                  "det_confidence": 0.9, "ocr_confidence": 0.95, "region": "IN"}]
                if do_plates else None
            ),
        }

    monkeypatch.setattr(vision_local, "analyze_image", fake_analyze)
    monkeypatch.setattr(vision_local, "release_models", lambda: None)
    return fake_analyze


async def _incident_with_plate(client, _fake_vision, distance_m=4.0):
    from app.storage import get_storage
    from app.tasks import _analyze_photos_async

    worker = await login(client, PHONES["w_prod1"])
    key = await get_storage().save(b"x", "jpg")
    body = {"category": "machine_breakdown", "department_code": "PRODUCTION", "photo_key": key,
            "gps_lat": 19.0, "gps_lng": 74.7, "distance_m": distance_m,
            "distance_method": "lidar", "distance_confidence": "high"}
    r = await client.post("/api/incidents", json=body, headers=worker)
    inc = r.json()
    await _analyze_photos_async("incident", inc["id"])
    return inc["id"], worker


async def test_analysis_returns_plate_scale(client, _fake_vision):
    inc_id, worker = await _incident_with_plate(client, _fake_vision, distance_m=4.0)
    r = await client.get(f"/api/incidents/{inc_id}/analysis", headers=worker)
    ps = r.json()["plate_scale"]
    assert ps is not None
    assert ps["est_distance_m"] == 4.0  # k1.2 * 0.5 / 0.15
    assert ps["ar_distance_m"] == 4.0
    assert ps["consistent"] is True


async def test_settings_expose_plate_scale(client):
    cgm = await login(client, PHONES["cgm"])
    r = await client.get("/api/admin/settings", headers=cgm)
    body = r.json()
    assert body["plate_scale_enabled"] is True
    assert body["plate_ref_width_m"] == 0.5
    assert body["plate_scale_k"] == 1.2


async def test_calibrate_from_incident(client, _fake_vision):
    # seeded CGM (0001) is a REAL top-management account → may mutate config
    inc_id, _ = await _incident_with_plate(client, _fake_vision, distance_m=6.0)
    cgm = await login(client, PHONES["cgm"])
    r = await client.post("/api/admin/plate-scale/calibrate", json={"incident_id": inc_id}, headers=cgm)
    assert r.status_code == 200, r.text
    # k = distance * w / ref = 6.0 * 0.15 / 0.5 = 1.8
    assert r.json()["plate_scale_k"] == 1.8
    # persisted
    s = await client.get("/api/admin/settings", headers=cgm)
    assert s.json()["plate_scale_k"] == 1.8


async def test_calibrate_candidates_lists_incident(client, _fake_vision):
    inc_id, _ = await _incident_with_plate(client, _fake_vision, distance_m=5.0)
    cgm = await login(client, PHONES["cgm"])
    r = await client.get("/api/admin/plate-scale/candidates", headers=cgm)
    assert r.status_code == 200
    ids = [c["id"] for c in r.json()]
    assert inc_id in ids


async def test_calibrate_manual_and_validation(client):
    cgm = await login(client, PHONES["cgm"])
    # manual (distance + width) → k = 8 * 0.1 / 0.5 = 1.6
    r = await client.post(
        "/api/admin/plate-scale/calibrate",
        json={"distance_m": 8.0, "plate_width_fraction": 0.1}, headers=cgm,
    )
    assert r.status_code == 200 and r.json()["plate_scale_k"] == 1.6
    # nothing provided → 400
    r2 = await client.post("/api/admin/plate-scale/calibrate", json={}, headers=cgm)
    assert r2.status_code == 400


async def test_worker_cannot_calibrate(client):
    worker = await login(client, PHONES["w_prod1"])
    r = await client.post(
        "/api/admin/plate-scale/calibrate",
        json={"distance_m": 8.0, "plate_width_fraction": 0.1}, headers=worker,
    )
    assert r.status_code == 403
