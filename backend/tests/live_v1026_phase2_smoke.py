"""v1.0.26 LIVE PRESENCE Phase 2 — live-HTTP spot-check against the sandbox
preview backend. NOT part of the in-repo pytest suite (which uses an isolated
test DB). Uses the demo CGM +919000000500 / OTP 123456."""
import os
import datetime as dt

import pytest
import requests

BASE = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/") if "EXPO_PUBLIC_BACKEND_URL" in os.environ else "https://hogo-backend-phase1.preview.emergentagent.com"
API = f"{BASE}/api"
DEMO_CGM_PHONE = "+919000000500"
DEMO_WORKER_PHONE = "+919000000001"
OTP = "123456"


def _login(phone: str) -> str:
    r = requests.post(f"{API}/auth/send-otp", json={"phone": phone}, timeout=15)
    assert r.status_code == 200, f"send-otp failed {r.status_code}: {r.text}"
    r = requests.post(f"{API}/auth/verify-otp", json={"phone": phone, "otp": OTP}, timeout=15)
    assert r.status_code == 200, f"verify-otp failed {r.status_code}: {r.text}"
    tok = r.json().get("access_token") or r.json().get("token")
    assert tok
    return tok


@pytest.fixture(scope="module")
def cgm_headers():
    return {"Authorization": f"Bearer {_login(DEMO_CGM_PHONE)}"}


@pytest.fixture(scope="module")
def worker_headers():
    return {"Authorization": f"Bearer {_login(DEMO_WORKER_PHONE)}"}


# -------- alerts endpoints --------
def test_alerts_default_open(cgm_headers):
    r = requests.get(f"{API}/presence/alerts", headers=cgm_headers, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "alerts" in body and "open_total" in body
    assert isinstance(body["alerts"], list)


def test_alerts_status_all(cgm_headers):
    r = requests.get(f"{API}/presence/alerts?status=all", headers=cgm_headers, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "alerts" in body


def test_alerts_status_resolved(cgm_headers):
    r = requests.get(f"{API}/presence/alerts?status=resolved", headers=cgm_headers, timeout=15)
    assert r.status_code == 200, r.text


def test_alerts_worker_forbidden(worker_headers):
    r = requests.get(f"{API}/presence/alerts", headers=worker_headers, timeout=15)
    assert r.status_code == 403, r.text


# -------- muster --------
def test_muster_ok(cgm_headers):
    r = requests.get(f"{API}/presence/muster", headers=cgm_headers, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "groups" in body
    for k in ("inside", "outside", "unknown"):
        assert k in body["groups"], f"missing group {k}"
    assert "counts" in body
    assert "generated_at" in body


def test_muster_worker_forbidden(worker_headers):
    r = requests.get(f"{API}/presence/muster", headers=worker_headers, timeout=15)
    assert r.status_code == 403


# -------- shift-summary --------
def test_shift_summary_today(cgm_headers):
    r = requests.get(f"{API}/presence/shift-summary", headers=cgm_headers, timeout=20)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "workers" in body and isinstance(body["workers"], list)


def test_shift_summary_future_400(cgm_headers):
    r = requests.get(f"{API}/presence/shift-summary?date=2099-01-01", headers=cgm_headers, timeout=15)
    assert r.status_code == 400, r.text


def test_shift_summary_worker_forbidden(worker_headers):
    r = requests.get(f"{API}/presence/shift-summary", headers=worker_headers, timeout=15)
    assert r.status_code == 403


# -------- timeline --------
def test_timeline_needs_valid_employee(cgm_headers):
    # 404 for random uuid
    r = requests.get(
        f"{API}/presence/timeline?employee_id=00000000-0000-0000-0000-000000000000",
        headers=cgm_headers, timeout=15,
    )
    assert r.status_code in (400, 404), r.text


def test_timeline_ok_for_real_worker(cgm_headers):
    # find any worker in muster or shift-summary
    r = requests.get(f"{API}/presence/shift-summary", headers=cgm_headers, timeout=15)
    workers = r.json().get("workers") or []
    if not workers:
        pytest.skip("no workers in shift-summary today")
    emp_id = workers[0].get("employee_id") or workers[0].get("id")
    if not emp_id:
        pytest.skip("worker row has no employee_id key")
    r = requests.get(f"{API}/presence/timeline?employee_id={emp_id}", headers=cgm_headers, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "worker" in body
    assert "segments" in body
    assert "points" in body


def test_timeline_worker_forbidden(worker_headers):
    r = requests.get(
        f"{API}/presence/timeline?employee_id=00000000-0000-0000-0000-000000000000",
        headers=worker_headers, timeout=15,
    )
    assert r.status_code == 403


# -------- ack/resolve (best-effort — requires an open alert) --------
def test_ack_then_resolve_if_available(cgm_headers):
    r = requests.get(f"{API}/presence/alerts", headers=cgm_headers, timeout=15)
    assert r.status_code == 200
    alerts = [a for a in r.json().get("alerts", []) if a.get("status") == "active"]
    if not alerts:
        pytest.skip("no active alert available to ack/resolve")
    aid = alerts[0]["id"]
    r = requests.post(f"{API}/presence/alerts/{aid}/ack", headers=cgm_headers, timeout=15)
    assert r.status_code in (200, 409), r.text
    if r.status_code == 200:
        assert r.json().get("status") == "acknowledged"
    r = requests.post(f"{API}/presence/alerts/{aid}/resolve", headers=cgm_headers, timeout=15)
    assert r.status_code in (200, 409), r.text
    if r.status_code == 200:
        assert r.json().get("status") == "resolved"
