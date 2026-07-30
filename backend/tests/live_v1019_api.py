"""
v1.0.19 WAVE 1 API spot-checks (backend already 231/231 pytest green — this file
is just live-URL sanity for the routes the mobile/webdash UI depend on).
Run:  cd /app/backend && python -m pytest tests/live_v1019_api.py -v -s
"""
import os
import time
import uuid
import pytest
import requests

BASE = os.environ.get("PUBLIC_URL", "https://hogo-backend-phase1.preview.emergentagent.com").rstrip("/")

DEMO = {
    "sec_worker": "+919000000011",   # SECURITY worker D011
    "sec_manager": "+919000000111",  # SECURITY manager D111
    "to_manager": "+919000000113",   # TIME_OFFICE manager D113
    "cgm": "+919000000500",          # Demo CGM D500
    "prod_worker": "+919000000010",  # PRODUCTION worker D010 (fallback check)
}


def _login(phone: str) -> dict:
    last_err = None
    for attempt in range(3):
        try:
            r = requests.post(f"{BASE}/api/auth/verify-otp",
                              json={"phone": phone, "otp": "123456"}, timeout=20)
            if r.status_code == 200:
                d = r.json()
                return {"token": d["access_token"], "employee": d.get("employee") or d.get("user") or {}, "raw": d}
            last_err = f"{r.status_code} {r.text[:200]}"
        except Exception as e:
            last_err = str(e)
        time.sleep(1.5)
    raise RuntimeError(f"verify-otp failed for {phone}: {last_err}")


def _auth(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def sessions():
    out = {}
    for k, p in DEMO.items():
        try:
            out[k] = _login(p)
        except Exception as e:
            out[k] = {"error": str(e)}
    return out


# ---------- HOME CONFIG resolution ----------
class TestHomeConfig:
    def test_sec_worker_gets_config(self, sessions):
        s = sessions["sec_worker"]; assert "token" in s, s
        r = requests.get(f"{BASE}/api/home/config", headers=_auth(s["token"]), timeout=10)
        assert r.status_code == 200, r.text
        cfg = r.json()
        assert cfg is not None, "SECURITY worker should have a config (dept-level)"
        widgets = cfg.get("widgets") or cfg.get("config", {}).get("widgets") or []
        wt = [w.get("type") for w in widgets]
        assert any(t in wt for t in ("count_tiles", "action_grid")), f"expected widgets, got {wt}"
        print("SEC WORKER config widgets:", wt)

    def test_to_manager_gets_config(self, sessions):
        s = sessions["to_manager"]; assert "token" in s, s
        r = requests.get(f"{BASE}/api/home/config", headers=_auth(s["token"]), timeout=10)
        assert r.status_code == 200
        cfg = r.json()
        assert cfg, "TO manager must have config"
        widgets = cfg.get("widgets") or cfg.get("config", {}).get("widgets") or []
        print("TO MANAGER config widgets:", [w.get("type") for w in widgets])

    def test_cgm_gets_config(self, sessions):
        s = sessions["cgm"]; assert "token" in s, s
        r = requests.get(f"{BASE}/api/home/config", headers=_auth(s["token"]), timeout=10)
        assert r.status_code == 200
        print("CGM config:", (r.json() or {}).get("name") or (r.json() or {}).get("id"))

    def test_prod_worker_fallback_null(self, sessions):
        s = sessions["prod_worker"]
        if "error" in s:
            pytest.skip(f"prod worker login failed: {s}")
        r = requests.get(f"{BASE}/api/home/config", headers=_auth(s["token"]), timeout=10)
        assert r.status_code == 200
        # PRODUCTION worker not covered by any (dept,role) or dept row → should be null
        body = r.json()
        assert body is None or body == {} or body.get("widgets") in (None, []), \
            f"PRODUCTION worker should fall back to default home, got: {body}"
        print("PROD WORKER config:", body)


# ---------- HOME COUNTS ----------
class TestHomeCounts:
    def test_counts_sec_worker(self, sessions):
        s = sessions["sec_worker"]
        r = requests.get(f"{BASE}/api/home/counts", headers=_auth(s["token"]), timeout=10)
        assert r.status_code == 200, r.text
        body = r.json()
        assert isinstance(body, dict)
        print("SEC WORKER counts:", body)

    def test_counts_to_manager(self, sessions):
        s = sessions["to_manager"]
        r = requests.get(f"{BASE}/api/home/counts", headers=_auth(s["token"]), timeout=10)
        assert r.status_code == 200
        body = r.json()
        print("TO MANAGER counts:", body)
        # tiles should be numeric (per review-request "not dashes")
        for k in ("pending_registrations", "flagged_attendance", "pending_submissions",
                  "phoneless_employees"):
            if k in body:
                assert isinstance(body[k], (int, float)), f"{k} not numeric: {body[k]!r}"


# ---------- VEHICLE LOG ACCESS CONTROL ----------
class TestVehicleAccess:
    def test_to_manager_forbidden(self, sessions):
        s = sessions["to_manager"]
        r = requests.get(f"{BASE}/api/vehicles/logs", headers=_auth(s["token"]), timeout=10)
        assert r.status_code == 403, f"TO manager should be 403 on vehicles/logs, got {r.status_code}: {r.text}"

    def test_cgm_allowed(self, sessions):
        s = sessions["cgm"]
        r = requests.get(f"{BASE}/api/vehicles/logs", headers=_auth(s["token"]), timeout=10)
        assert r.status_code == 200, r.text
        j = r.json()
        assert "logs" in j or isinstance(j, list), f"unexpected: {j}"
        print("CGM vehicles/logs sample rows:", len(j.get("logs", j) if isinstance(j, dict) else j))

    def test_sec_worker_allowed(self, sessions):
        s = sessions["sec_worker"]
        r = requests.get(f"{BASE}/api/vehicles/logs", headers=_auth(s["token"]), timeout=10)
        assert r.status_code == 200


# ---------- VEHICLE E2E (IN + OUT pairing + idempotency) ----------
class TestVehicleE2E:
    plate = "MH45TA2001"

    def test_post_in(self, sessions):
        s = sessions["sec_worker"]
        r = requests.post(f"{BASE}/api/vehicles/log", headers=_auth(s["token"]), json={
            "plate": "MH 45 TA 2001",
            "direction": "in",
            "vehicle_type": "tractor",
            "purpose": "cane",
            "client_uuid": str(uuid.uuid4()),
        }, timeout=15)
        assert r.status_code in (200, 201), f"IN log failed: {r.status_code} {r.text}"
        body = r.json()
        log = body.get("log", body)
        # plate should be normalised (spaces removed, uppercase)
        assert (log.get("plate") or "").replace(" ", "").upper() == self.plate, body

    def test_inside_lists_plate(self, sessions):
        s = sessions["sec_worker"]
        r = requests.get(f"{BASE}/api/vehicles/inside", headers=_auth(s["token"]), timeout=10)
        assert r.status_code == 200, r.text
        j = r.json()
        rows = j if isinstance(j, list) else j.get("logs") or j.get("inside") or []
        plates = [(row.get("plate") or "").replace(" ", "").upper() for row in rows]
        assert self.plate in plates, f"plate {self.plate} not in inside list: {plates[:20]}"

    def test_idempotent_client_uuid(self, sessions):
        s = sessions["sec_worker"]
        cid = str(uuid.uuid4())
        payload = {"plate": "MH 45 TA 9999", "direction": "in", "vehicle_type": "tractor",
                   "purpose": "cane", "client_uuid": cid}
        r1 = requests.post(f"{BASE}/api/vehicles/log", headers=_auth(s["token"]), json=payload, timeout=10)
        r2 = requests.post(f"{BASE}/api/vehicles/log", headers=_auth(s["token"]), json=payload, timeout=10)
        assert r1.status_code in (200, 201)
        assert r2.status_code in (200, 201, 409)
        # both should return same id (idempotency)
        if r1.status_code < 300 and r2.status_code < 300:
            id1 = r1.json().get("id") or r1.json().get("log_id")
            id2 = r2.json().get("id") or r2.json().get("log_id")
            if id1 and id2:
                assert id1 == id2, f"idempotency failed: {id1} != {id2}"

    def test_post_out_pairing(self, sessions):
        s = sessions["sec_worker"]
        r = requests.post(f"{BASE}/api/vehicles/log", headers=_auth(s["token"]), json={
            "plate": self.plate, "direction": "out", "vehicle_type": "tractor",
            "purpose": "cane", "client_uuid": str(uuid.uuid4()),
        }, timeout=15)
        assert r.status_code in (200, 201), r.text

        # After OUT it should NOT be in inside list
        r2 = requests.get(f"{BASE}/api/vehicles/inside", headers=_auth(s["token"]), timeout=10)
        j = r2.json()
        rows = j if isinstance(j, list) else j.get("logs") or j.get("inside") or []
        plates = [(row.get("plate") or "").replace(" ", "").upper() for row in rows]
        assert self.plate not in plates, f"{self.plate} still in inside after OUT: {plates[:20]}"

    def test_summary(self, sessions):
        s = sessions["sec_worker"]
        r = requests.get(f"{BASE}/api/vehicles/summary", headers=_auth(s["token"]), timeout=10)
        assert r.status_code == 200
        print("summary keys:", list((r.json() or {}).keys()))

    def test_export_xlsx(self, sessions):
        s = sessions["cgm"]
        r = requests.get(f"{BASE}/api/vehicles/export.xlsx", headers=_auth(s["token"]), timeout=20)
        assert r.status_code == 200, r.text[:200]
        assert len(r.content) > 100, "xlsx body too small"
        # xlsx magic bytes = PK\x03\x04
        assert r.content[:2] == b"PK", f"not an xlsx: first bytes={r.content[:4]!r}"


# ---------- INCIDENTS PAGINATION ----------
class TestIncidentsPagination:
    def test_limit_two(self, sessions):
        s = sessions["cgm"]
        r = requests.get(f"{BASE}/api/incidents?limit=2", headers=_auth(s["token"]), timeout=10)
        assert r.status_code == 200, r.text
        j = r.json()
        rows = j if isinstance(j, list) else j.get("incidents") or j.get("items") or []
        assert len(rows) <= 2, f"expected ≤2, got {len(rows)}"

    def test_default_still_works(self, sessions):
        s = sessions["cgm"]
        r = requests.get(f"{BASE}/api/incidents", headers=_auth(s["token"]), timeout=10)
        assert r.status_code == 200
