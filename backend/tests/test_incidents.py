from sqlalchemy import text

from app.escalation import run_escalation_sweep
from tests.conftest import PHONES, login


async def _create_incident(client, headers, dept="PRODUCTION", category="machine_breakdown"):
    r = await client.post(
        "/api/incidents",
        json={"category": category, "department_code": dept, "photo_key": "inc.jpg",
              "gps_lat": 19.0, "gps_lng": 74.7, "description": "test incident"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    return r.json()


async def test_incident_assigned_to_dept_manager(client, db_session):
    headers = await login(client, PHONES["w_prod1"])
    inc = await _create_incident(client, headers)
    mgr_id = (
        await db_session.execute(text("SELECT id FROM employees WHERE phone=:p"), {"p": PHONES["prod_mgr"]})
    ).scalar()
    assert inc["assigned_manager_id"] == str(mgr_id)
    assert inc["status"] == "submitted"


async def test_incident_without_dept_manager_goes_to_cgm(client, db_session):
    headers = await login(client, PHONES["w_prod1"])
    inc = await _create_incident(client, headers, dept="CANE_YARD")
    cgm_id = (
        await db_session.execute(text("SELECT id FROM employees WHERE phone=:p"), {"p": PHONES["cgm"]})
    ).scalar()
    assert inc["assigned_manager_id"] == str(cgm_id)


async def test_incidents_mine(client):
    headers = await login(client, PHONES["w_prod1"])
    r = await client.get("/api/incidents/mine", headers=headers)
    assert r.status_code == 200
    assert len(r.json()) >= 1


async def test_incident_detail_includes_timeline(client):
    headers = await login(client, PHONES["w_prod1"])
    inc = await _create_incident(client, headers)
    r = await client.get(f"/api/incidents/{inc['id']}", headers=headers)
    assert r.status_code == 200
    timeline = r.json()["timeline"]
    assert len(timeline) >= 1
    assert timeline[0]["event"] == "created"


async def test_manager_updates_status_with_timeline_and_audit(client, db_session):
    w_headers = await login(client, PHONES["w_prod1"])
    inc = await _create_incident(client, w_headers)
    m_headers = await login(client, PHONES["prod_mgr"])
    r = await client.post(
        f"/api/incidents/{inc['id']}/status", json={"status": "seen"}, headers=m_headers
    )
    assert r.status_code == 200
    assert r.json()["status"] == "seen"
    r = await client.post(
        f"/api/incidents/{inc['id']}/status",
        json={"status": "resolved", "note": "fixed the belt"},
        headers=m_headers,
    )
    assert r.json()["status"] == "resolved"
    assert r.json()["resolution_note"] == "fixed the belt"
    audit = (
        await db_session.execute(
            text("SELECT COUNT(*) FROM audit_events WHERE action='incident.status_change' AND entity_id=:e"),
            {"e": inc["id"]},
        )
    ).scalar()
    assert audit == 2
    detail = await client.get(f"/api/incidents/{inc['id']}", headers=m_headers)
    events = [t["event"] for t in detail.json()["timeline"]]
    assert "seen" in events and "status_change" in events


async def test_worker_cannot_update_status(client):
    headers = await login(client, PHONES["w_prod1"])
    inc = await _create_incident(client, headers)
    r = await client.post(f"/api/incidents/{inc['id']}/status", json={"status": "seen"}, headers=headers)
    assert r.status_code == 403


async def test_incident_list_role_scoping(client):
    m_headers = await login(client, PHONES["prod_mgr"])
    r = await client.get("/api/incidents", headers=m_headers)
    assert all(i["department_code"] == "PRODUCTION" for i in r.json())
    cgm_headers = await login(client, PHONES["cgm"])
    r = await client.get("/api/incidents", headers=cgm_headers)
    depts = {i["department_code"] for i in r.json()}
    assert "CANE_YARD" in depts  # CGM sees everything


async def test_escalation_sweep_escalates_stale_incident(client, db_session):
    headers = await login(client, PHONES["w_prod1"])
    inc = await _create_incident(client, headers)
    await db_session.execute(
        text("UPDATE incidents SET created_at = NOW() - INTERVAL '49 hours' WHERE id = CAST(:i AS uuid)"),
        {"i": inc["id"]},
    )
    await db_session.commit()
    counts = await run_escalation_sweep(db_session)
    await db_session.commit()
    assert counts["incidents_escalated"] >= 1
    row = (
        await db_session.execute(
            text("SELECT status, escalated_to FROM incidents WHERE id = CAST(:i AS uuid)"), {"i": inc["id"]}
        )
    ).first()
    cgm_id = (
        await db_session.execute(text("SELECT id FROM employees WHERE phone=:p"), {"p": PHONES["cgm"]})
    ).scalar()
    assert row[0] == "escalated"
    assert row[1] == cgm_id
    notif = (
        await db_session.execute(
            text("SELECT COUNT(*) FROM notifications WHERE recipient_id=:r AND type='incident_escalated' AND entity_id=:e"),
            {"r": cgm_id, "e": inc["id"]},
        )
    ).scalar()
    assert notif >= 1


async def test_escalation_without_md_stays_with_cgm(client, db_session):
    headers = await login(client, PHONES["w_prod1"])
    inc = await _create_incident(client, headers)
    await db_session.execute(
        text("UPDATE incidents SET created_at = NOW() - INTERVAL '49 hours' WHERE id = CAST(:i AS uuid)"),
        {"i": inc["id"]},
    )
    await db_session.commit()
    await run_escalation_sweep(db_session)
    await db_session.commit()
    # age the escalation itself — second sweep would go to MD, but no MD exists
    await db_session.execute(
        text("UPDATE incidents SET escalated_at = NOW() - INTERVAL '49 hours' WHERE id = CAST(:i AS uuid)"),
        {"i": inc["id"]},
    )
    await db_session.commit()
    counts = await run_escalation_sweep(db_session)
    await db_session.commit()
    assert counts["incidents_to_md"] == 0
    row = (
        await db_session.execute(
            text("SELECT status, escalated_to FROM incidents WHERE id = CAST(:i AS uuid)"), {"i": inc["id"]}
        )
    ).first()
    cgm_id = (
        await db_session.execute(text("SELECT id FROM employees WHERE phone=:p"), {"p": PHONES["cgm"]})
    ).scalar()
    assert row[0] == "escalated" and row[1] == cgm_id  # gracefully kept with CGM


async def test_escalation_sweep_escalates_stale_submission(client, db_session):
    headers = await login(client, PHONES["w_prod1"])
    forms = await client.get("/api/forms", headers=headers)
    form_id = next(f["id"] for f in forms.json() if f["code"] == "hourly_process_log")
    sub = await client.post(
        f"/api/forms/{form_id}/submit",
        json={"data_json": {"station": "lab", "brix_value": 10}},
        headers=headers,
    )
    sub_id = sub.json()["id"]
    await db_session.execute(
        text("UPDATE form_submissions SET created_at = NOW() - INTERVAL '49 hours' WHERE id = CAST(:i AS uuid)"),
        {"i": sub_id},
    )
    await db_session.commit()
    counts = await run_escalation_sweep(db_session)
    await db_session.commit()
    assert counts["submissions_escalated"] >= 1
    status = (
        await db_session.execute(
            text("SELECT status FROM form_submissions WHERE id = CAST(:i AS uuid)"), {"i": sub_id}
        )
    ).scalar()
    assert status == "escalated"
