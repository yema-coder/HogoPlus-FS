"""v1.0.19: GET /api/admin/emp-id-suggest must ignore garbage 6-7 digit legacy
emp_ids (e.g. 300312, 3003200) and suggest from the normal 4-digit pool."""
from app.models import Employee

from .conftest import PHONES, login


async def test_emp_id_suggest_ignores_outliers(client, db_session):
    db_session.add(
        Employee(
            emp_id="3003200", full_name="Legacy Garbage", phone="+919111111321",
            department_code="PRODUCTION", designation="Worker PRODUCTION",
            role_code="Worker", language_pref="mr", shift_swap_eligible=False,
            onboarding_status="approved", is_active=True,
        )
    )
    await db_session.commit()

    to = await login(client, PHONES["time_mgr"])
    r = await client.get("/api/admin/emp-id-suggest", headers=to)
    assert r.status_code == 200
    suggested = r.json()["suggested_emp_id"]
    assert len(suggested) == 4, f"outlier leaked into suggestion: {suggested}"
    assert int(suggested) < 10000
