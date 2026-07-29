"""TASK A: register 23 indoor iBeacons on PRODUCTION (api.hogoplus.in) via the admin
bulk endpoint, then set Hindi/Marathi zone labels via PATCH. Idempotent (bulk skips
existing minors; PATCH by matching minor)."""
import json
import urllib.request

BASE = "https://api.hogoplus.in/api"
UUID = "01122334-4556-6778-899A-ABBCCDDEEFF0"

# minor -> (en, hi, mr)
ZONES = {
    29: ("Manufacturing Office", "निर्माण कार्यालय", "निर्मिती कार्यालय"),
    27: ("Engineering Office", "इंजीनियरिंग कार्यालय", "अभियांत्रिकी कार्यालय"),
    12: ("Unloader", "अनलोडर", "अनलोडर"),
    2: ("Mill Section", "मिल सेक्शन", "मिल विभाग"),
    3: ("Mill No.5", "मिल क्रमांक ५", "मिल क्रमांक ५"),
    22: ("Boiler", "बॉयलर", "बॉयलर"),
    14: ("Turbine & Powerhouse", "टर्बाइन और पावरहाउस", "टर्बाइन आणि पॉवरहाऊस"),
    17: ("DCS Office", "डीसीएस कार्यालय", "डीसीएस कार्यालय"),
    5: ("Boiling House", "बॉयलिंग हाउस", "बॉयलिंग हाऊस"),
    25: ("Admin Office", "प्रशासन कार्यालय", "प्रशासन कार्यालय"),
    16: ("Agriculture Office", "कृषि कार्यालय", "शेती कार्यालय"),
    35: ("Accounts Office", "लेखा कार्यालय", "लेखा कार्यालय"),
    0: ("Civil", "सिविल", "सिव्हिल"),
    1: ("Circulator Room", "सर्कुलेटर कक्ष", "सर्क्युलेटर रूम"),
    30: ("Distillery Turbine", "डिस्टिलरी टर्बाइन", "डिस्टिलरी टर्बाइन"),
    9: ("Distillery Boiler", "डिस्टिलरी बॉयलर", "डिस्टिलरी बॉयलर"),
    11: ("Distillery New Office", "डिस्टिलरी नया कार्यालय", "डिस्टिलरी नवीन कार्यालय"),
    31: ("PSO", "पीएसओ", "पीएसओ"),
    19: ("Non-PSO", "नॉन-पीएसओ", "नॉन-पीएसओ"),
    28: ("PLC Plus Room", "पीएलसी प्लस कक्ष", "पीएलसी प्लस रूम"),
    23: ("PCTP", "पीसीटीपी", "पीसीटीपी"),
    20: ("Guest House", "गेस्ट हाउस", "गेस्ट हाऊस"),
    21: ("Main Office", "मुख्य कार्यालय", "मुख्य कार्यालय"),
}
PRE_EXISTING = {33, 18, 7, 34, 4, 15}


def call(method: str, path: str, body=None, token=None):
    req = urllib.request.Request(BASE + path, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    data = json.dumps(body).encode() if body is not None else None
    with urllib.request.urlopen(req, data=data, timeout=30) as r:
        return json.loads(r.read().decode())


def main() -> None:
    tok = call("POST", "/auth/password-login", {"emp_id": "0001", "password": "Hogo@2026Cgm"})[
        "access_token"
    ]
    print("CGM login: OK")

    rows = [{"minor": m, "zone_name": en} for m, (en, _h, _m) in ZONES.items()]
    res = call("POST", "/admin/beacons/bulk", {"beacon_uuid": UUID, "major": 1, "rows": rows}, tok)
    print("bulk import:", res)

    beacons = call("GET", "/admin/beacons", token=tok)
    print(f"registry total rows: {len(beacons)}")

    # PATCH hi/mr labels on the 23 new rows only (never touch the pre-existing 6)
    patched = 0
    for b in beacons:
        m = b.get("minor")
        if m in ZONES and m not in PRE_EXISTING:
            en, hi, mr = ZONES[m]
            call(
                "PATCH",
                f"/admin/beacons/{b['id']}",
                {"zone_label_en": en, "zone_label_hi": hi, "zone_label_mr": mr},
                tok,
            )
            patched += 1
    print(f"labels patched: {patched}")

    # final state
    beacons = call("GET", "/admin/beacons", token=tok)
    print(f"\nFINAL REGISTRY ({len(beacons)} rows):")
    for b in sorted(beacons, key=lambda x: (x["minor"] is None, x["minor"])):
        print(
            f"  minor={b['minor']:<3} active={b['is_active']} en={b['zone_label_en']} | "
            f"hi={b['zone_label_hi']} | mr={b['zone_label_mr']}"
        )

    reg = call("GET", "/attendance/beacon-registry", token=tok)
    minors = sorted(i["minor"] for i in reg["ibeacons"])
    print(f"\nmobile beacon-registry endpoint: {len(reg['ibeacons'])} ibeacons, minors={minors}")
    print("minor 0 present in mobile registry:", 0 in minors)


main()
