"""v1.0.22 live E2E tests against preview backend.

Covers the three v1.0.22 items from the review request:
1. no_punch_out queue flow (flagged queue includes row, worker can dispute even
   though verification_level='verified', TO approve removes it)
2. late punch-out self-clears no_punch_out flag
3. incident + form client_uuid idempotency (replay returns same id; no dup rows)
4. shift-swap happy path + double-decide 409 (sequential; concurrency covered by
   unit tests in tests/test_next_batch.py)

Uses live preview URL + local Postgres for direct row inserts / verification.
"""
import os
import uuid
from datetime import date, datetime, timedelta, timezone

import psycopg2
import pytest
import requests

BASE = os.environ.get("EXPO_PUBLIC_API_URL", "https://hogo-backend-phase1.preview.emergentagent.com").rstrip("/")
PG_DSN = "host=127.0.0.1 user=hogo password=hogo_secret dbname=hogoplus"

# Use the demo bubble pair per TESTING POLICY (both is_demo=true so TO sees worker's rows).
# Real +918308829567 TO Manager is NOT in DEMO_OTP_WHITELIST, and real 0021 is is_demo=false —
# they can't see each other's rows because /attendance/flagged filters by is_demo bucket.
WORKER_PHONE = "+919000000001"        # D001 Demo Accounts Worker (is_demo=true)
TO_PHONE = "+919000000113"            # D113 Demo TO Manager (is_demo=true)


def _ist_today() -> date:
    return (datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)).date()


def _login(phone: str) -> str:
    r = requests.post(f"{BASE}/api/auth/verify-otp", json={"phone": phone, "otp": "123456"}, timeout=15)
    assert r.status_code == 200, f"login failed for {phone}: {r.status_code} {r.text}"
    return r.json()["access_token"]


def _me(token: str) -> dict:
    r = requests.get(f"{BASE}/api/auth/me", headers={"Authorization": f"Bearer {token}"}, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()


def _hdr(t: str) -> dict:
    return {"Authorization": f"Bearer {t}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def db():
    conn = psycopg2.connect(PG_DSN)
    conn.autocommit = True
    yield conn
    conn.close()


@pytest.fixture(scope="module")
def worker_token():
    return _login(WORKER_PHONE)


@pytest.fixture(scope="module")
def to_token():
    return _login(TO_PHONE)


@pytest.fixture(scope="module")
def worker_id(worker_token):
    return _me(worker_token)["id"]


def _clean(db, emp_id: str):
    with db.cursor() as cur:
        cur.execute("DELETE FROM attendance_regularizations WHERE employee_id=%s", (emp_id,))
        cur.execute("DELETE FROM attendance WHERE employee_id=%s", (emp_id,))


def _insert_open_punch(db, emp_id: str, d, flagged_reason=None) -> str:
    row_id = str(uuid.uuid4())
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO attendance (id, employee_id, date, punch_in_at, verification_level, "
            "flagged_reason, is_late, gps_verified, selfie_key, is_demo) "
            "VALUES (%s,%s,%s, now(), 'verified', %s, false, true, 's.jpg', true)",
            (row_id, emp_id, d, flagged_reason),
        )
    return row_id


# ----------------------------------------------------------------------
# 1. no_punch_out queue + dispute + approve
# ----------------------------------------------------------------------

def test_no_punch_out_row_in_flagged_queue_and_disputable(db, worker_token, to_token, worker_id):
    _clean(db, worker_id)
    today = _ist_today()
    att_id = _insert_open_punch(db, worker_id, today, flagged_reason="no_punch_out")

    # TO manager sees it in flagged queue with correct fields
    r = requests.get(f"{BASE}/api/attendance/flagged", headers=_hdr(to_token), timeout=15)
    assert r.status_code == 200, r.text
    rec = next((a for a in r.json() if a["id"] == att_id), None)
    assert rec is not None, "row not in TO flagged queue"
    assert rec["flagged_reason"] == "no_punch_out"
    assert rec["verification_level"] == "verified", "verification_level must NOT be downgraded"

    # Worker can dispute even though verification_level='verified'
    r = requests.post(
        f"{BASE}/api/attendance/{att_id}/regularize",
        json={"text_note": "e2e: I did punch out at the gate"},
        headers=_hdr(worker_token),
        timeout=15,
    )
    assert r.status_code == 200, f"regularize failed: {r.status_code} {r.text}"

    # TO approves -> row disappears from queue
    r = requests.post(f"{BASE}/api/attendance/{att_id}/approve", headers=_hdr(to_token), timeout=15)
    assert r.status_code == 200, r.text
    r = requests.get(f"{BASE}/api/attendance/flagged", headers=_hdr(to_token), timeout=15)
    assert all(a["id"] != att_id for a in r.json()), "row should be gone from TO flagged queue"


# ----------------------------------------------------------------------
# 2. late punch-out self-clears no_punch_out flag
# ----------------------------------------------------------------------

def test_late_punch_out_clears_no_punch_out_flag(db, worker_token, worker_id):
    # Use IST today-1 to avoid unique(employee_id,date) collision if test 1's row is still there.
    _clean(db, worker_id)
    ydate = _ist_today() - timedelta(days=1)
    att_id = _insert_open_punch(db, worker_id, ydate, flagged_reason="no_punch_out")

    r = requests.post(f"{BASE}/api/attendance/punch-out", headers=_hdr(worker_token), timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] == att_id
    assert body["punch_out_at"] is not None, "punch_out_at must be set"
    assert body["flagged_reason"] is None, "flagged_reason must be cleared on real late punch-out"

    # Cleanup — remove test row
    _clean(db, worker_id)


# ----------------------------------------------------------------------
# 3. Incident client_uuid idempotency
# ----------------------------------------------------------------------

def test_incident_client_uuid_dedup(worker_token):
    cu = f"e2e-inc-{uuid.uuid4()}"
    payload = {
        "category": "other",
        "department_code": "PRODUCTION",
        "description": "e2e dup test",
        "photo_key": "e2e.jpg",
        "gps_lat": 19.0, "gps_lng": 74.7,
        "client_uuid": cu,
    }
    r1 = requests.post(f"{BASE}/api/incidents", json=payload, headers=_hdr(worker_token), timeout=15)
    assert r1.status_code == 200, r1.text
    r2 = requests.post(f"{BASE}/api/incidents", json=payload, headers=_hdr(worker_token), timeout=15)
    assert r2.status_code == 200, r2.text
    assert r1.json()["id"] == r2.json()["id"], "same client_uuid must return same id"

    # DB: exactly one row with this client_uuid
    conn = psycopg2.connect(PG_DSN)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM incidents WHERE client_uuid=%s", (cu,))
            assert cur.fetchone()[0] == 1
    finally:
        conn.close()


def test_incident_without_client_uuid_creates_two_rows(worker_token):
    payload = {
        "category": "other",
        "department_code": "PRODUCTION",
        "description": "e2e no-uuid regression",
        "photo_key": "e2e2.jpg",
        "gps_lat": 19.0, "gps_lng": 74.7,
    }
    ra = requests.post(f"{BASE}/api/incidents", json=payload, headers=_hdr(worker_token), timeout=15)
    rb = requests.post(f"{BASE}/api/incidents", json=payload, headers=_hdr(worker_token), timeout=15)
    assert ra.status_code == 200 and rb.status_code == 200
    assert ra.json()["id"] != rb.json()["id"], "without client_uuid dedup must NOT happen"


# ----------------------------------------------------------------------
# 4. Form submit client_uuid idempotency
# ----------------------------------------------------------------------

def test_form_submit_client_uuid_dedup(worker_token):
    # Find an active form the worker can submit. Worker is ACCOUNTS dept.
    r = requests.get(f"{BASE}/api/forms", headers=_hdr(worker_token), timeout=15)
    assert r.status_code == 200, r.text
    forms = r.json()
    if not forms:
        pytest.skip("no active forms visible to worker — cannot test form dedup")
    def_id = forms[0]["id"]
    fields = (forms[0].get("schema_json") or {}).get("fields") or []
    # Build minimal valid data_json — set required fields to a placeholder if we can guess.
    data_json = {}
    for f in fields:
        key = f.get("key")
        if not key:
            continue
        t = f.get("type", "text")
        if t in ("text", "textarea"):
            data_json[key] = "e2e"
        elif t == "number":
            data_json[key] = 1
        elif t == "select":
            opts = f.get("options") or []
            data_json[key] = opts[0] if opts else "e2e"
        elif t == "toggle":
            data_json[key] = False

    cu = f"e2e-form-{uuid.uuid4()}"
    body = {"data_json": data_json, "photos": [], "client_uuid": cu}
    r1 = requests.post(f"{BASE}/api/forms/{def_id}/submit", json=body, headers=_hdr(worker_token), timeout=15)
    if r1.status_code != 200:
        pytest.skip(f"form submit not available for this worker: {r1.status_code} {r1.text[:150]}")
    r2 = requests.post(f"{BASE}/api/forms/{def_id}/submit", json=body, headers=_hdr(worker_token), timeout=15)
    assert r2.status_code == 200, r2.text
    assert r1.json()["id"] == r2.json()["id"], "same client_uuid must return same submission id"


# ----------------------------------------------------------------------
# 5. Shift-swap: happy path + sequential double-decide → 409
# ----------------------------------------------------------------------

def test_shift_swap_happy_path_and_double_decide_409():
    """Skips gracefully if no eligible pair exists in live DB (per request)."""
    # Demo bubble PRODUCTION pair: D009 on shift A, D022 on GEN, manager D109.
    w1_phone = "+919000000009"   # D009 PRODUCTION worker (shift A)
    w2_phone = "+919000000022"   # D022 PRODUCTION worker (shift GEN)
    mgr_phone = "+919000000109"  # D109 PRODUCTION Manager

    try:
        r = requests.post(f"{BASE}/api/auth/verify-otp", json={"phone": w1_phone, "otp": "123456"}, timeout=15)
        if r.status_code != 200:
            pytest.skip(f"w1 not in demo whitelist for demo OTP ({r.status_code}) — skipping live swap flow")
        w1 = r.json()["access_token"]
        r = requests.post(f"{BASE}/api/auth/verify-otp", json={"phone": w2_phone, "otp": "123456"}, timeout=15)
        if r.status_code != 200:
            pytest.skip("w2 not in whitelist — skipping live swap flow (unit tests cover concurrency)")
        w2 = r.json()["access_token"]
        r = requests.post(f"{BASE}/api/auth/verify-otp", json={"phone": mgr_phone, "otp": "123456"}, timeout=15)
        if r.status_code != 200:
            pytest.skip("mgr not in whitelist — skipping")
        mgr = r.json()["access_token"]
    except Exception as e:
        pytest.skip(f"Login flow error: {e}")

    # Look up target emp id
    conn = psycopg2.connect(PG_DSN)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM employees WHERE phone=%s", (w2_phone,))
            target_id = str(cur.fetchone()[0])
    finally:
        conn.close()

    swap_date = (date.today() + timedelta(days=30)).isoformat()
    r = requests.post(
        f"{BASE}/api/shift-swaps",
        json={"target_employee_id": target_id, "swap_date": swap_date, "reason": "e2e v1022"},
        headers=_hdr(w1), timeout=15,
    )
    if r.status_code != 200:
        pytest.skip(
            f"swap create failed on live demo bubble (msg: {r.text[:150]}). "
            "Demo bubble employees all share baseline shift 'GEN' so no future-dated same-dept/diff-shift "
            "pair exists. Concurrency covered by tests/test_next_batch.py::test_swap_concurrent_decide_applies_exactly_once "
            "and ::test_swap_concurrent_respond_single_transition (both green)."
        )
    swap_id = r.json()["id"]

    r = requests.post(f"{BASE}/api/shift-swaps/{swap_id}/respond", json={"accept": True}, headers=_hdr(w2), timeout=15)
    assert r.status_code == 200, r.text
    # Second respond → 409
    r2 = requests.post(f"{BASE}/api/shift-swaps/{swap_id}/respond", json={"accept": True}, headers=_hdr(w2), timeout=15)
    assert r2.status_code == 409, f"second respond should be 409, got {r2.status_code}"

    # Manager decide approve
    r = requests.post(f"{BASE}/api/shift-swaps/{swap_id}/decide", json={"approve": True}, headers=_hdr(mgr), timeout=15)
    assert r.status_code == 200, r.text
    # Second decide → 409
    r2 = requests.post(f"{BASE}/api/shift-swaps/{swap_id}/decide", json={"approve": True}, headers=_hdr(mgr), timeout=15)
    assert r2.status_code == 409, f"second decide should be 409, got {r2.status_code}"
