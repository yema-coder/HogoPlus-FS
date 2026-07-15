"""Phase 5 — MD Command Center endpoints + role scoping (mandatory)."""
import pytest

from tests.conftest import PHONES, login

pytestmark = pytest.mark.asyncio


async def test_worker_gets_403_on_all_dashboard_endpoints(client):
    headers = await login(client, PHONES["w_prod1"])
    for path in [
        "/api/dashboard/overview",
        "/api/dashboard/department/PRODUCTION",
        "/api/dashboard/approvals-aging",
        "/api/dashboard/reports",
        "/api/dashboard/audit",
    ]:
        r = await client.get(path, headers=headers)
        assert r.status_code == 403, path


async def test_manager_overview_scoped_to_own_dept(client):
    headers = await login(client, PHONES["prod_mgr"])
    r = await client.get("/api/dashboard/overview", headers=headers)
    assert r.status_code == 200
    data = r.json()
    assert [d["code"] for d in data["departments"]] == ["PRODUCTION"]
    assert all(i["department_code"] == "PRODUCTION" for i in data["incidents"])
    assert set(data["kpis"]) >= {"present", "total", "attendance_pct", "late", "flagged",
                                 "open_incidents", "critical_incidents", "pending_approvals",
                                 "submissions_today"}


async def test_cgm_overview_sees_all_departments(client):
    headers = await login(client, PHONES["cgm"])
    r = await client.get("/api/dashboard/overview", headers=headers)
    assert r.status_code == 200
    data = r.json()
    assert len(data["departments"]) >= 2
    for tile in data["departments"]:
        assert tile["health"] in ("red", "amber", "green")


async def test_manager_cannot_open_other_dept_drilldown(client):
    headers = await login(client, PHONES["prod_mgr"])
    r = await client.get("/api/dashboard/department/ENGINEERING", headers=headers)
    assert r.status_code == 403
    r = await client.get("/api/dashboard/department/PRODUCTION", headers=headers)
    assert r.status_code == 200
    data = r.json()
    assert data["code"] == "PRODUCTION"
    assert len(data["trends"]) == 14
    assert {"attendance", "submissions", "incidents", "manager_name"} <= set(data)


async def test_approvals_aging_scoping_and_shape(client):
    mgr = await client.get(
        "/api/dashboard/approvals-aging", headers=await login(client, PHONES["prod_mgr"])
    )
    assert mgr.status_code == 200
    assert all(i["department_code"] == "PRODUCTION" for i in mgr.json()["items"])

    cgm = await client.get(
        "/api/dashboard/approvals-aging", headers=await login(client, PHONES["cgm"])
    )
    assert cgm.status_code == 200
    data = cgm.json()
    ages = [i["age_hours"] for i in data["items"]]
    assert ages == sorted(ages, reverse=True)  # oldest first
    assert isinstance(data["summary"], list)


async def test_reports_and_audit_cgm_only(client):
    mgr_headers = await login(client, PHONES["prod_mgr"])
    assert (await client.get("/api/dashboard/reports", headers=mgr_headers)).status_code == 403
    assert (await client.get("/api/dashboard/audit", headers=mgr_headers)).status_code == 403

    cgm_headers = await login(client, PHONES["cgm"])
    r = await client.get("/api/dashboard/reports", headers=cgm_headers)
    assert r.status_code == 200 and "reports" in r.json()
    r = await client.get("/api/dashboard/audit?limit=10", headers=cgm_headers)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


async def test_ai_usage_includes_7day_history(client):
    r = await client.get("/api/admin/ai-usage", headers=await login(client, PHONES["cgm"]))
    assert r.status_code == 200
    data = r.json()
    assert len(data["history"]) == 7
    assert {"date", "total", "counts"} <= set(data["history"][0])


async def test_health_reports_db_seeded(client):
    r = await client.get("/api/health")
    assert r.status_code == 200
    assert "db_seeded" in r.json()
