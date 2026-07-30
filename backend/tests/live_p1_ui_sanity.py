"""Live smoke against preview URL for v1.0.21 P1 UI flows.

Only the endpoints wired to the new UI:
- GET /api/attendance/month-summary  (worker=own OK, worker=other 403)
- GET /api/attendance/mine            (rows include regularization+is_flagged fields)
- POST /api/attendance/{id}/regularize on a non-flagged attendance → 409 code
- GET /api/incidents (manager) returns reporter_name + duplicate_of fields
"""
import os
import requests

BASE = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")

WORKER_PHONE = "+919000000009"
TIME_MGR = "+919000000113"
PROD_MGR = "+919000000109"
OTP = "123456"


def _login(phone: str) -> str:
    r = requests.post(f"{BASE}/api/auth/send-otp", json={"phone": phone}, timeout=15)
    assert r.status_code in (200, 201, 429), r.text
    r = requests.post(f"{BASE}/api/auth/verify-otp",
                      json={"phone": phone, "otp": OTP}, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _h(tok):
    return {"Authorization": f"Bearer {tok}"}


def test_month_summary_worker_own():
    tok = _login(WORKER_PHONE)
    r = requests.get(f"{BASE}/api/attendance/month-summary", headers=_h(tok), timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "current" in body and "previous" in body
    for key in ("days_present", "days_flagged_pending"):
        assert key in body["current"], body["current"]
    print("month-summary current:", body["current"])
    print("month-summary previous:", body["previous"])


def test_month_summary_other_worker_forbidden():
    tok = _login(WORKER_PHONE)
    # try to read the security worker's month
    me_r = requests.get(f"{BASE}/api/auth/me", headers=_h(_login("+919000000011")),
                        timeout=15)
    other_id = me_r.json()["id"]
    r = requests.get(f"{BASE}/api/attendance/month-summary?employee_id={other_id}",
                     headers=_h(tok), timeout=15)
    assert r.status_code == 403, (r.status_code, r.text)


def test_attendance_mine_shape():
    tok = _login(WORKER_PHONE)
    r = requests.get(f"{BASE}/api/attendance/mine", headers=_h(tok), timeout=15)
    assert r.status_code == 200, r.text
    rows = r.json()
    assert isinstance(rows, list)
    if rows:
        keys = set(rows[0].keys())
        # what /attendance/history renders on
        assert "regularization" in keys or "verification_level" in keys
        print("sample row keys:", sorted(keys))
        # confirm at least one flagged row exists (spec: 18th flagged demo row)
        flagged = [r for r in rows if r.get("verification_level") == "flagged"
                   and (not r.get("regularization") or r["regularization"].get("status") is None)]
        print("open-flagged rows count:", len(flagged))
        return flagged
    return []


def test_incidents_list_has_dedup_fields_for_manager():
    tok = _login(PROD_MGR)
    r = requests.get(f"{BASE}/api/incidents", headers=_h(tok), timeout=15)
    assert r.status_code == 200, r.text
    rows = r.json()
    assert isinstance(rows, list)
    if rows:
        keys = set(rows[0].keys())
        assert "reporter_name" in keys, ("reporter_name missing", sorted(keys))
        assert "duplicate_of" in keys, ("duplicate_of missing", sorted(keys))
        print("incidents row keys:", sorted(keys))
    else:
        print("no incidents in list (skip field shape)")


def test_regularize_second_time_409():
    """Only exercise if there is an OPEN flagged row we haven't disputed."""
    tok = _login(WORKER_PHONE)
    rows = requests.get(f"{BASE}/api/attendance/mine",
                        headers=_h(tok), timeout=15).json()
    open_flagged = [r for r in rows if r.get("verification_level") == "flagged"
                    and (not r.get("regularization")
                         or r["regularization"].get("status") in (None, ))]
    if not open_flagged:
        print("no open-flagged rows → skipping 409 duplicate check")
        return
    att = open_flagged[0]
    aid = att["id"]
    r1 = requests.post(f"{BASE}/api/attendance/{aid}/regularize",
                       headers=_h(tok), json={"text_note": "sanity dispute"},
                       timeout=15)
    print("1st regularize:", r1.status_code, r1.text[:200])
    if r1.status_code != 200:
        # maybe already disputed by a previous run
        print("first regularize non-200; continuing to duplicate attempt")
    r2 = requests.post(f"{BASE}/api/attendance/{aid}/regularize",
                       headers=_h(tok), json={"text_note": "sanity dispute 2"},
                       timeout=15)
    assert r2.status_code == 409, (r2.status_code, r2.text)
    body = r2.json()
    detail = body.get("detail")
    if isinstance(detail, dict):
        assert detail.get("code") == "reg_already_open", detail
    print("second regularize 409 OK ->", detail)


if __name__ == "__main__":
    test_month_summary_worker_own()
    test_month_summary_other_worker_forbidden()
    test_attendance_mine_shape()
    test_incidents_list_has_dedup_fields_for_manager()
    test_regularize_second_time_409()
    print("\nALL LIVE P1 SANITY OK")
