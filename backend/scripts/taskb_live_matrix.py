"""TASK B live evidence: the 6-case matrix punched by DEMO workers with the flag OFF
and ON, against the frozen-code backend + PRODUCTION DB. Demo rows are class-isolated
and auto-purge in 60 min. EC2 prod backend (old code) ignores the flag column, so the
factory is untouched while it is ON here. Flag is ALWAYS reverted to OFF at the end."""
import json
import urllib.error
import urllib.request

BASE = "http://localhost:8001/api"
UUID = "01122334-4556-6778-899A-ABBCCDDEEFF0"
BOILER = {"ble_ibeacon_uuid": UUID, "ble_ibeacon_major": 1, "ble_ibeacon_minor": 22}
INSIDE = {"gps_lat": 19.3134, "gps_lng": 74.7093}   # inside 1200m prod geofence
OUTSIDE = {"gps_lat": 18.5204, "gps_lng": 73.8567}  # Pune, far outside

CASES = [
    ("beacon + GPS-inside", {**INSIDE, **BOILER}),
    ("beacon + GPS-outside", {**OUTSIDE, **BOILER}),
    ("beacon + no-GPS", {**BOILER}),
    ("no-beacon + GPS-inside", {**INSIDE}),
    ("no-beacon + GPS-outside", {**OUTSIDE}),
    ("no-beacon + no-GPS", {}),
]
# 12 distinct demo workers (one punch/day each); 001 already punched today (minor-0 proof)
WORKERS = [f"+9190000000{n:02d}" for n in (2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13)]


def call(method, path, body=None, token=None):
    req = urllib.request.Request(BASE + path, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    data = json.dumps(body).encode() if body is not None else None
    with urllib.request.urlopen(req, data=data, timeout=30) as r:
        return json.loads(r.read().decode())


def demo_login(phone):
    try:
        call("POST", "/auth/send-otp", {"phone": phone})
    except urllib.error.HTTPError:
        pass
    return call("POST", "/auth/verify-otp", {"phone": phone, "otp": "123456"})["access_token"]


def main() -> None:
    cgm = call("POST", "/auth/password-login", {"emp_id": "0001", "password": "Hogo@2026Cgm"})[
        "access_token"
    ]
    wi = iter(WORKERS)
    try:
        for flag in (False, True):
            s = call("PATCH", "/admin/settings", {"beacon_first_mode": flag}, cgm)
            print(f"\n===== FLAG {'ON' if flag else 'OFF'} (settings.beacon_first_mode={s['beacon_first_mode']}) =====")
            for label, payload in CASES:
                phone = next(wi)
                tok = demo_login(phone)
                body = {"selfie_key": "demo-seed-beacon-first-evidence.jpg", **payload}
                try:
                    rec = call("POST", "/attendance/punch-in", body, tok)
                except urllib.error.HTTPError as e:
                    print(f"  {label:<26} {phone}: HTTP {e.code} {e.read().decode()[:120]}")
                    continue
                print(
                    f"  {label:<26} -> level={rec['verification_level']:<14} "
                    f"reason={rec['flagged_reason'] or '-':<26} zone={rec['ble_zone'] or '-':<8} "
                    f"gps_stored={rec['gps_lat'] is not None} gps_verified={rec['gps_verified']}"
                )
    finally:
        s = call("PATCH", "/admin/settings", {"beacon_first_mode": False}, cgm)
        print(f"\nflag reverted: beacon_first_mode={s['beacon_first_mode']} (must be False)")


main()
