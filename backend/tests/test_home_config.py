"""Wave 1 — config-driven home: flag gating, dept/role resolution order,
fallback (None) behaviour, admin upsert, and the aggregate counts endpoint."""
from sqlalchemy import text

from tests.conftest import PHONES, login

SEC_HOME = {
    "widgets": [
        {"type": "count_tiles", "items": [
            {"key": "vehicles_today_in", "label": {"en": "In today", "hi": "आज अंदर", "mr": "आज आत"}},
            {"key": "vehicles_inside", "label": {"en": "Inside", "hi": "अंदर", "mr": "आत"}},
        ]},
        {"type": "action_grid", "items": [
            {"icon": "Truck", "label": {"en": "Vehicle entry", "hi": "वाहन एंट्री", "mr": "वाहन नोंद"},
             "route": "/vehicle/new", "testID": "w-vehicle-new"},
        ]},
    ]
}


async def _enable_flag(db_session):
    await db_session.execute(text("UPDATE settings SET home_config_enabled=true"))
    await db_session.commit()


async def test_no_config_returns_null_fallback(client, db_session):
    await _enable_flag(db_session)
    worker = await login(client, PHONES["w_prod1"])
    r = await client.get("/api/home/config", headers=worker)
    assert r.status_code == 200
    assert r.json()["config"] is None  # app renders its built-in home


async def test_flag_off_hides_config_from_real_users(client, db_session):
    await db_session.execute(text("UPDATE settings SET home_config_enabled=false"))
    await db_session.commit()
    cgm = await login(client, PHONES["cgm"])
    r = await client.put(
        "/api/admin/home-configs",
        json={"department_code": "SECURITY", "role_code": None, "config_json": SEC_HOME},
        headers=cgm,
    )
    assert r.status_code == 200, r.text
    sec = await login(client, PHONES["w_sec"])
    r2 = await client.get("/api/home/config", headers=sec)
    assert r2.json()["config"] is None  # flag OFF -> fallback even with a config saved


async def test_dept_config_resolution_and_update_without_apk(client, db_session):
    await _enable_flag(db_session)
    cgm = await login(client, PHONES["cgm"])
    await client.put(
        "/api/admin/home-configs",
        json={"department_code": "SECURITY", "role_code": None, "config_json": SEC_HOME},
        headers=cgm,
    )
    sec = await login(client, PHONES["w_sec"])
    cfg = (await client.get("/api/home/config", headers=sec)).json()["config"]
    assert cfg["widgets"][1]["items"][0]["route"] == "/vehicle/new"

    # dept+role beats dept-only for the manager
    mgr_home = {"widgets": [{"type": "count_tiles", "items": [{"key": "vehicles_inside", "label": {"en": "Inside", "hi": "x", "mr": "x"}}]}]}
    await client.put(
        "/api/admin/home-configs",
        json={"department_code": "SECURITY", "role_code": "Manager", "config_json": mgr_home},
        headers=cgm,
    )
    hod = await login(client, PHONES["sec_mgr"])
    cfg2 = (await client.get("/api/home/config", headers=hod)).json()["config"]
    assert len(cfg2["widgets"]) == 1  # got the (dept, role) layout, not the dept one

    # config edit = layout change with NO app build
    changed = {"widgets": [{"type": "action_grid", "items": [{"icon": "Shield", "label": {"en": "Patrol", "hi": "x", "mr": "x"}, "route": "/attendance/punch"}]}]}
    await client.put(
        "/api/admin/home-configs",
        json={"department_code": "SECURITY", "role_code": None, "config_json": changed},
        headers=cgm,
    )
    cfg3 = (await client.get("/api/home/config", headers=sec)).json()["config"]
    assert cfg3["widgets"][0]["type"] == "action_grid"


async def test_admin_upsert_requires_rank2_and_widgets_shape(client):
    worker = await login(client, PHONES["w_prod1"])
    r = await client.put(
        "/api/admin/home-configs",
        json={"department_code": "SECURITY", "role_code": None, "config_json": SEC_HOME},
        headers=worker,
    )
    assert r.status_code == 403
    cgm = await login(client, PHONES["cgm"])
    r2 = await client.put(
        "/api/admin/home-configs",
        json={"department_code": "SECURITY", "role_code": None, "config_json": {"nope": 1}},
        headers=cgm,
    )
    assert r2.status_code == 422


async def test_home_counts_role_aware(client, db_session):
    worker = await login(client, PHONES["w_prod1"])
    c_worker = (await client.get("/api/home/counts", headers=worker)).json()
    assert "pending_registrations" not in c_worker  # workers get no manager numbers

    tm = await login(client, PHONES["time_mgr"])
    # an earlier suite test may have filled the seeded phone-less worker's phone —
    # re-null it so the TO count has a guaranteed subject
    await db_session.execute(text("UPDATE employees SET phone=NULL WHERE emp_id='0120'"))
    await db_session.commit()
    c_tm = (await client.get("/api/home/counts", headers=tm)).json()
    assert "pending_registrations" in c_tm and "flagged_attendance" in c_tm
    assert "phoneless_employees" in c_tm
    assert c_tm["phoneless_employees"] >= 1  # conftest seeds a phone-less worker

    cgm = await login(client, PHONES["cgm"])
    c_cgm = (await client.get("/api/home/counts", headers=cgm)).json()
    for key in ("present_today", "open_incidents", "vehicles_today_in", "vehicles_inside"):
        assert key in c_cgm

    sec = await login(client, PHONES["w_sec"])
    c_sec = (await client.get("/api/home/counts", headers=sec)).json()
    assert "vehicles_today_in" in c_sec and "pending_registrations" not in c_sec
