"""MINOR-0 LIVE E2E: punch in on PRODUCTION (api.hogoplus.in) as a DEMO worker with
the exact iBeacon payload the app would send for minor 0 (Civil). Demo rows are
class-isolated and auto-purge after 60 min. Proves no falsy/zero bug end-to-end."""
import json
import urllib.error
import urllib.request

BASE = "http://localhost:8001/api"
UUID = "01122334-4556-6778-899A-ABBCCDDEEFF0"
DEMO_WORKERS = [f"+9190000000{n:02d}" for n in (1, 2, 3, 4, 5, 21, 22, 23, 24)]


def call(method, path, body=None, token=None):
    req = urllib.request.Request(BASE + path, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    data = json.dumps(body).encode() if body is not None else None
    with urllib.request.urlopen(req, data=data, timeout=30) as r:
        return json.loads(r.read().decode())


def login(phone):
    try:
        call("POST", "/auth/send-otp", {"phone": phone})
    except urllib.error.HTTPError:
        pass  # rate-limited resend is fine; demo verify doesn't need the stored OTP
    return call("POST", "/auth/verify-otp", {"phone": phone, "otp": "123456"})["access_token"]


def main() -> None:
    payload = {
        "gps_lat": 19.3134,
        "gps_lng": 74.7093,
        "selfie_key": "demo-seed-minor0-e2e.jpg",
        "ble_ibeacon_uuid": UUID,
        "ble_ibeacon_major": 1,
        "ble_ibeacon_minor": 0,  # <-- the zero under test
    }
    for phone in DEMO_WORKERS:
        tok = login(phone)
        try:
            rec = call("POST", "/attendance/punch-in", payload, tok)
        except urllib.error.HTTPError as e:
            if e.code == 409:
                print(f"{phone}: already punched today, trying next demo worker")
                continue
            body = e.read().decode()[:200]
            print(f"{phone}: HTTP {e.code} {body}")
            if e.code == 422:
                print("payload rejected — inspect:", json.dumps(payload))
                return
            continue
        print("PUNCH ACCEPTED on PRODUCTION:")
        print(f"  ble_beacon_id (stored ref): {rec.get('ble_beacon_id')}")
        print(f"  ble_zone:                   {rec.get('ble_zone')}")
        print(f"  verification_level:         {rec.get('verification_level')}")
        print(f"  flagged_reason:             {rec.get('flagged_reason')}")
        ok = rec.get("ble_zone") == "Civil" and rec.get("verification_level") == "verified_plus"
        print(f"  MINOR-0 E2E: {'PASS' if ok else 'FAIL'}")
        return
    print("no demo worker available for a fresh punch today")


main()
