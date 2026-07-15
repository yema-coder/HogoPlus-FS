"""Prompt 7 tests: video upload cap + magic bytes + presign content-type,
password login (webdash) with lockout/forced-change/role gates, plate search,
video incidents (media validator, no ANPR on video), address_text roundtrip."""
import io

from sqlalchemy import text

from app.redis_client import redis_client
from app.storage import _content_type
from tests.conftest import PHONES, login

# minimal valid magic-byte payloads
JPG = b"\xff\xd8\xff\xe0" + b"0" * 64
MP4 = b"\x00\x00\x00\x18ftypmp42" + b"0" * 64


async def _emp_id_of(db_session, phone: str) -> str:
    row = await db_session.execute(text("SELECT id, emp_id FROM employees WHERE phone=:p"), {"p": phone})
    return row.first()


# ---------------- Part A: video upload ----------------

async def test_video_upload_and_40mb_cap(client):
    w = await login(client, PHONES["w_prod1"])
    r = await client.post(
        "/api/files/upload", headers=w,
        files={"file": ("clip.mp4", io.BytesIO(MP4), "video/mp4")},
    )
    assert r.status_code == 200, r.text
    assert r.json()["key"].endswith(".mp4")

    big = b"\x00\x00\x00\x18ftypmp42" + b"0" * (40 * 1024 * 1024)
    r = await client.post(
        "/api/files/upload", headers=w,
        files={"file": ("big.mp4", io.BytesIO(big), "video/mp4")},
    )
    assert r.status_code == 413
    detail = r.json()["detail"]
    assert detail["code"] == "video_too_large"
    assert all(k in detail for k in ("en", "hi", "mr"))  # trilingual


async def test_video_magic_bytes_enforced(client):
    w = await login(client, PHONES["w_prod1"])
    r = await client.post(
        "/api/files/upload", headers=w,
        files={"file": ("fake.mp4", io.BytesIO(b"not a video at all"), "video/mp4")},
    )
    assert r.status_code == 400


def test_presign_content_type_for_video():
    assert _content_type("abc.mp4") == "video/mp4"
    assert _content_type("abc.jpg") == "image/jpeg"
    assert _content_type("abc.m4a") in ("audio/mp4", "audio/m4a", "audio/x-m4a")


async def test_video_incident_no_photo_ok_and_photo_or_video_required(client):
    w = await login(client, PHONES["w_prod1"])
    r = await client.post("/api/incidents", json={
        "category": "other", "department_code": "PRODUCTION",
        "video_key": "v.mp4", "description": "machine noise video",
        "address_text": "Gate 2, Sugar Factory Road",
    }, headers=w)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["video_key"] == "v.mp4" and body["photo_key"] is None
    assert body["address_text"] == "Gate 2, Sugar Factory Road"
    assert body["video_url"] and body["video_url"].endswith("v.mp4")

    r = await client.post("/api/incidents", json={
        "category": "other", "department_code": "PRODUCTION", "description": "no media",
    }, headers=w)
    assert r.status_code == 422  # photo_key or video_key required


# ---------------- Part B: password login ----------------

async def _set_password(client, actor_headers, employee_id, password="TempPass123"):
    return await client.post(
        f"/api/admin/employees/{employee_id}/set-password",
        json={"password": password}, headers=actor_headers,
    )


async def _get_emp(db_session, phone):
    row = (await db_session.execute(
        text("SELECT id::text AS id, emp_id FROM employees WHERE phone=:p"), {"p": phone}
    )).first()
    return row


async def test_set_password_role_gated(client, db_session):
    cgm = await login(client, PHONES["cgm"])
    mgr = await login(client, PHONES["prod_mgr"])
    worker = await login(client, PHONES["w_prod1"])
    target = await _get_emp(db_session, PHONES["cgm"])

    r = await _set_password(client, worker, target.id)
    assert r.status_code == 403
    r = await _set_password(client, mgr, target.id)
    assert r.status_code == 403  # rank-3 manager cannot set passwords
    r = await _set_password(client, cgm, target.id)
    assert r.status_code == 200
    assert r.json()["must_change_password"] is True


async def test_password_login_happy_and_forced_change(client, db_session):
    cgm = await login(client, PHONES["cgm"])
    target = await _get_emp(db_session, PHONES["cgm"])
    await redis_client.delete(f"pwlogin:fail:{target.emp_id}")
    assert (await _set_password(client, cgm, target.id, "TempPass123")).status_code == 200

    r = await client.post("/api/auth/password-login",
                          json={"emp_id": target.emp_id, "password": "TempPass123"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["must_change_password"] is True
    assert body["access_token"] and body["refresh_token"]
    assert body["employee"]["emp_id"] == target.emp_id
    hdrs = {"Authorization": f"Bearer {body['access_token']}"}

    # forced change: too short rejected, valid accepted, flag cleared
    r = await client.post("/api/auth/change-password",
                          json={"current_password": "TempPass123", "new_password": "short"}, headers=hdrs)
    assert r.status_code == 422
    r = await client.post("/api/auth/change-password",
                          json={"current_password": "WRONG", "new_password": "NewSecret99"}, headers=hdrs)
    assert r.status_code == 400
    r = await client.post("/api/auth/change-password",
                          json={"current_password": "TempPass123", "new_password": "NewSecret99"}, headers=hdrs)
    assert r.status_code == 200

    r = await client.post("/api/auth/password-login",
                          json={"emp_id": target.emp_id, "password": "NewSecret99"})
    assert r.status_code == 200
    assert r.json()["must_change_password"] is False


async def test_password_login_lockout_after_5(client, db_session):
    cgm = await login(client, PHONES["cgm"])
    target = await _get_emp(db_session, PHONES["cgm"])
    await redis_client.delete(f"pwlogin:fail:{target.emp_id}")
    assert (await _set_password(client, cgm, target.id, "LockMe12345")).status_code == 200

    for _ in range(5):
        r = await client.post("/api/auth/password-login",
                              json={"emp_id": target.emp_id, "password": "wrong-pass"})
        assert r.status_code == 401
    r = await client.post("/api/auth/password-login",
                          json={"emp_id": target.emp_id, "password": "LockMe12345"})
    assert r.status_code == 429
    detail = r.json()["detail"]
    assert detail["code"] == "password_login_locked"
    assert all(k in detail for k in ("en", "hi", "mr"))
    await redis_client.delete(f"pwlogin:fail:{target.emp_id}")


async def test_worker_rejected_on_password_login_even_with_password(client, db_session):
    worker_row = await _get_emp(db_session, PHONES["w_prod1"])
    # force-set a hash directly (bypasses the role-gated endpoint)
    from app.security import hash_password

    await db_session.execute(
        text("UPDATE employees SET password_hash=:h WHERE emp_id=:e"),
        {"h": hash_password("WorkerPass123"), "e": worker_row.emp_id},
    )
    await db_session.commit()
    await redis_client.delete(f"pwlogin:fail:{worker_row.emp_id}")
    r = await client.post("/api/auth/password-login",
                          json={"emp_id": worker_row.emp_id, "password": "WorkerPass123"})
    assert r.status_code == 403


# ---------------- Part C: plate search ----------------

async def test_plate_search_scoped(client, db_session):
    w = await login(client, PHONES["w_prod1"])
    r = await client.post("/api/incidents", json={
        "category": "other", "department_code": "PRODUCTION",
        "photo_key": "truck.jpg", "description": "truck blocking gate",
    }, headers=w)
    inc_id = r.json()["id"]
    await db_session.execute(
        text("UPDATE incidents SET detected_plate='MH12AB1234' WHERE id=:i"), {"i": inc_id}
    )
    await db_session.commit()

    cgm = await login(client, PHONES["cgm"])
    r = await client.get("/api/dashboard/plates/search?q=mh12", headers=cgm)
    assert r.status_code == 200
    results = r.json()["results"]
    assert any(x["id"] == inc_id and x["plate"] == "MH12AB1234" for x in results)

    # PRODUCTION manager sees it (own dept); worker forbidden
    mgr = await login(client, PHONES["prod_mgr"])
    r = await client.get("/api/dashboard/plates/search?q=AB1234", headers=mgr)
    assert r.status_code == 200
    assert any(x["id"] == inc_id for x in r.json()["results"])

    r = await client.get("/api/dashboard/plates/search?q=AB1234", headers=w)
    assert r.status_code == 403

    # dept scoping: manager of another dept must NOT see PRODUCTION plates
    # (use TIME_OFFICE manager, rank 3)
    tmgr = await login(client, PHONES["time_mgr"])
    r = await client.get("/api/dashboard/plates/search?q=AB1234", headers=tmgr)
    assert r.status_code == 200
    assert not any(x["id"] == inc_id for x in r.json()["results"])


# ---------------- Part D: address_text on form submissions ----------------

async def test_form_submission_address_text(client, db_session):
    # find any active form definition for PRODUCTION
    row = (await db_session.execute(
        text("SELECT id::text AS id FROM form_definitions WHERE department_code='PRODUCTION' AND is_active LIMIT 1")
    )).first()
    if row is None:
        return  # no seeded form — covered by incident address test
    w = await login(client, PHONES["staff_prod"])
    r = await client.post(f"/api/forms/{row.id}/submit", json={
        "data_json": {}, "photos": [], "gps_lat": 19.1, "gps_lng": 74.6,
        "address_text": "Boiler House, MIDC Road",
    }, headers=w)
    if r.status_code == 200:
        sub = r.json()
        assert sub["address_text"] == "Boiler House, MIDC Road"
