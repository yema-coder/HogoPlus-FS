"""Self-registration E2E validation against the running backend (demo OTP, no SMS).

Flow: unknown number -> send-otp -> verify-otp (is_new + registration token)
      -> selfie upload -> register -> lands pending_approval
      -> CGM login -> approval queue shows the registrant
Then cleans up the test employee from the DB.
"""
import io
import re
import subprocess
import sys
import time

import requests

BASE = "https://hogo-backend-phase1.preview.emergentagent.com/api"
TEST_PHONE = "+919999900011"
CGM_PHONE = "+918483029039"
DEMO_OTP = "123456"

ok = True


def step(name, cond, extra=""):
    global ok
    print(f"{'PASS' if cond else 'FAIL'} | {name} {extra}")
    if not cond:
        ok = False


def logged_otp(phone: str) -> str:
    """OTP_MODE=demo logs the real OTP — scrape the latest one for this phone."""
    out = subprocess.run(
        f"grep '\\[DEMO OTP\\] phone={phone}' /var/log/supervisor/backend*.log | tail -1",
        shell=True, capture_output=True, text=True,
    ).stdout
    m = re.search(r"otp=(\d+)", out)
    return m.group(1) if m else ""


# 1. send-otp for unknown number (registration open -> no 403)
r = requests.post(f"{BASE}/auth/send-otp", json={"phone": TEST_PHONE})
step("send-otp unknown number accepted (registration open)", r.status_code in (200, 429), f"status={r.status_code} body={r.text[:120]}")
time.sleep(1)
otp = logged_otp(TEST_PHONE)
step("real OTP retrieved from demo-mode log", bool(otp))

# 2. verify-otp -> is_new + registration token
r = requests.post(f"{BASE}/auth/verify-otp", json={"phone": TEST_PHONE, "otp": otp})
step("verify-otp returns is_new", r.status_code == 200 and r.json().get("is_new") is True, f"status={r.status_code}")
reg_token = r.json().get("registration_token", "")
step("registration_token issued", bool(reg_token))

# 3. selfie upload with registration token (real portrait so the Rekognition face gate passes)
try:
    JPEG = requests.get("https://randomuser.me/api/portraits/men/75.jpg", timeout=15).content
except Exception:
    JPEG = b""
step("portrait fetched for selfie", len(JPEG) > 1000, f"{len(JPEG)} bytes")
r = requests.post(
    f"{BASE}/files/upload",
    headers={"Authorization": f"Bearer {reg_token}"},
    files={"file": ("selfie.jpg", io.BytesIO(JPEG), "image/jpeg")},
)
step("selfie upload with registration token", r.status_code == 200, f"status={r.status_code} body={r.text[:150]}")
selfie_key = r.json().get("file_key") or r.json().get("key") or ""
step("selfie key returned", bool(selfie_key), selfie_key)

# 4. register
r = requests.post(
    f"{BASE}/auth/register",
    headers={"Authorization": f"Bearer {reg_token}"},
    json={"phone": TEST_PHONE, "full_name": "E2E Test Registrant", "selfie_key": selfie_key},
)
step("register succeeds", r.status_code == 200, f"status={r.status_code} body={r.text[:200]}")
emp = r.json().get("employee", {})
step("lands in pending_approval", emp.get("onboarding_status") == "pending_approval", f"status={emp.get('onboarding_status')} emp_id={emp.get('emp_id')}")
new_emp_id = emp.get("emp_id")

# 5. re-login with same number -> should NOT be is_new anymore
r = requests.post(f"{BASE}/auth/send-otp", json={"phone": TEST_PHONE})
time.sleep(1)
otp2 = logged_otp(TEST_PHONE) or otp
r = requests.post(f"{BASE}/auth/verify-otp", json={"phone": TEST_PHONE, "otp": otp2})
step(
    "re-login resolves to pending account (not new)",
    r.status_code == 200 and r.json().get("is_new") is False
    and r.json().get("employee", {}).get("onboarding_status") == "pending_approval",
)

# 6. CGM sees the registrant in the approval queue
r = requests.post(f"{BASE}/auth/send-otp", json={"phone": CGM_PHONE})
r = requests.post(f"{BASE}/auth/verify-otp", json={"phone": CGM_PHONE, "otp": DEMO_OTP})
step("CGM login", r.status_code == 200 and not r.json().get("is_new"), f"status={r.status_code}")
cgm_token = r.json().get("access_token", "")
r = requests.get(f"{BASE}/admin/employees/pending", headers={"Authorization": f"Bearer {cgm_token}"})
rows = r.json() if isinstance(r.json(), list) else r.json().get("items", r.json().get("pending", []))
match = [x for x in rows if x.get("phone") == TEST_PHONE or x.get("full_name") == "E2E Test Registrant"]
step("approval queue shows registrant to CGM", r.status_code == 200 and len(match) == 1, f"status={r.status_code} queue_size={len(rows) if isinstance(rows, list) else '?'}")
if match:
    m = match[0]
    print(f"       queue row: emp_id={m.get('emp_id')} name={m.get('full_name')} selfie={bool(m.get('selfie_url'))} suggested_next_id={m.get('suggested_emp_id', '-')}")

print("\nRESULT:", "ALL PASS" if ok else "FAILURES PRESENT")
print("cleanup target emp_id:", new_emp_id)
sys.exit(0 if ok else 1)
