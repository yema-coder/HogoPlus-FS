from datetime import date, timedelta

from sqlalchemy import text

from tests.conftest import PHONES, employee_id_by_phone, login


def _d(offset: int) -> str:
    return (date.today() + timedelta(days=offset)).isoformat()


async def test_shifts_mine(client):
    headers = await login(client, PHONES["w_prod1"])
    r = await client.get("/api/shifts/mine", headers=headers)
    assert r.status_code == 200
    days = r.json()
    assert len(days) == 8
    assert days[0]["shift_code"] == "A"


async def test_swap_happy_path(client, db_session):
    w1 = await login(client, PHONES["w_prod1"])
    w2 = await login(client, PHONES["w_prod2"])
    mgr = await login(client, PHONES["prod_mgr"])
    target_id = await employee_id_by_phone(db_session, PHONES["w_prod2"])
    swap_date = _d(1)

    r = await client.post(
        "/api/shift-swaps",
        json={"target_employee_id": target_id, "swap_date": swap_date, "reason": "family function"},
        headers=w1,
    )
    assert r.status_code == 200, r.text
    swap = r.json()
    assert swap["status"] == "pending_target"

    r = await client.post(f"/api/shift-swaps/{swap['id']}/respond", json={"accept": True}, headers=w2)
    assert r.status_code == 200
    assert r.json()["status"] == "pending_manager"

    r = await client.get("/api/shift-swaps/pending", headers=mgr)
    assert any(s["id"] == swap["id"] for s in r.json())

    r = await client.post(f"/api/shift-swaps/{swap['id']}/decide", json={"approve": True}, headers=mgr)
    assert r.status_code == 200
    assert r.json()["status"] == "approved"

    # assignments swapped for that date only
    r = await client.get("/api/shifts/mine", headers=w1)
    tomorrow = next(d for d in r.json() if d["date"] == swap_date)
    assert tomorrow["shift_code"] == "B"
    day_after = next(d for d in r.json() if d["date"] == _d(2))
    assert day_after["shift_code"] == "A"  # baseline untouched
    r = await client.get("/api/shifts/mine", headers=w2)
    assert next(d for d in r.json() if d["date"] == swap_date)["shift_code"] == "A"

    # both sides audited
    audits = (
        await db_session.execute(
            text("SELECT COUNT(*) FROM audit_events WHERE action='shift_swap.applied' AND detail_json->>'swap_id'=:s"),
            {"s": swap["id"]},
        )
    ).scalar()
    assert audits == 2


async def test_swap_ineligible_employee(client, db_session):
    w1 = await login(client, PHONES["w_prod1"])
    staff_id = await employee_id_by_phone(db_session, PHONES["staff_prod"])
    r = await client.post(
        "/api/shift-swaps", json={"target_employee_id": staff_id, "swap_date": _d(3)}, headers=w1
    )
    assert r.status_code == 400
    assert "eligible" in r.json()["detail"]


async def test_swap_different_department_rejected(client, db_session):
    w1 = await login(client, PHONES["w_prod1"])
    eng_id = await employee_id_by_phone(db_session, PHONES["w_eng"])
    r = await client.post(
        "/api/shift-swaps", json={"target_employee_id": eng_id, "swap_date": _d(3)}, headers=w1
    )
    assert r.status_code == 400
    assert "department" in r.json()["detail"]


async def test_swap_same_shift_rejected(client, db_session):
    w1 = await login(client, PHONES["w_prod1"])
    w3_id = await employee_id_by_phone(db_session, PHONES["w_prod3"])
    r = await client.post(
        "/api/shift-swaps", json={"target_employee_id": w3_id, "swap_date": _d(3)}, headers=w1
    )
    assert r.status_code == 400
    assert "same shift" in r.json()["detail"]


async def test_swap_target_declines(client, db_session):
    w1 = await login(client, PHONES["w_prod1"])
    w2 = await login(client, PHONES["w_prod2"])
    target_id = await employee_id_by_phone(db_session, PHONES["w_prod2"])
    r = await client.post(
        "/api/shift-swaps", json={"target_employee_id": target_id, "swap_date": _d(4)}, headers=w1
    )
    swap = r.json()
    r = await client.post(f"/api/shift-swaps/{swap['id']}/respond", json={"accept": False}, headers=w2)
    assert r.status_code == 200
    assert r.json()["status"] == "rejected"


async def test_worker_cannot_decide_swap(client, db_session):
    w1 = await login(client, PHONES["w_prod1"])
    w2 = await login(client, PHONES["w_prod2"])
    w3 = await login(client, PHONES["w_prod3"])
    target_id = await employee_id_by_phone(db_session, PHONES["w_prod2"])
    r = await client.post(
        "/api/shift-swaps", json={"target_employee_id": target_id, "swap_date": _d(5)}, headers=w1
    )
    swap = r.json()
    await client.post(f"/api/shift-swaps/{swap['id']}/respond", json={"accept": True}, headers=w2)
    r = await client.post(f"/api/shift-swaps/{swap['id']}/decide", json={"approve": True}, headers=w3)
    assert r.status_code == 403
