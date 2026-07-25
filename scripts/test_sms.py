#!/usr/bin/env python3
"""Standalone SMSGatewayHub diagnostic — Prompt 21 Bug 1 (OTP not reaching gateway).

Run ON THE EC2 HOST (no dependencies beyond Python 3 stdlib):

    cd /opt/hogoplus
    python3 scripts/test_sms.py                       # lint .env + show effective OTP config
    python3 scripts/test_sms.py --send +91XXXXXXXXXX  # ALSO send ONE real test SMS (uses credits)
    python3 scripts/test_sms.py --env-file /path/to/.env

What it does:
  1. Parses the .env file strictly and LINTS it for exactly the failure modes that
     make docker-compose env injection silently drop variables:
       BOM, CRLF line endings, unbalanced quotes (multi-line swallow), spaces
       around '=', duplicate keys, inline comments, concatenated keys (missing
       newline before an appended line).
  2. Prints the effective OTP configuration (API key masked).
  3. --send: calls the SMSGatewayHub SendSMS API directly (urllib, GET) with those
     values and prints the RAW HTTP status + response body.
  4. Prints the docker commands to compare the host .env against what the running
     container actually received.
"""
from __future__ import annotations

import argparse
import random
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

SMSGATEWAYHUB_URL = "https://www.smsgatewayhub.com/api/mt/SendSMS"
OTP_KEYS = [
    "OTP_MODE", "DEMO_OTP_ENABLED", "DEMO_OTP", "DEMO_OTP_WHITELIST",
    "ALLOW_NEW_REGISTRATION", "SMSGATEWAYHUB_API_KEY", "SMSGATEWAYHUB_SENDER_ID",
    "SMSGATEWAYHUB_DLT_TEMPLATE_ID", "SMSGATEWAYHUB_ENTITY_ID", "OTP_TEMPLATE_TEXT",
    "OTP_MAX_PER_WINDOW", "OTP_WINDOW_MINUTES", "OTP_RESEND_COOLDOWN_SECONDS",
]
KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def mask(value: str, keep: int = 4) -> str:
    if not value:
        return "(EMPTY)"
    return value[:keep] + "****" if len(value) > keep else "****"


def lint_and_parse(path: Path) -> dict[str, str]:
    """Parse KEY=VALUE lines the way compose-go/dotenv roughly does, and print a
    WARNING for every construct known to break env injection."""
    problems: list[str] = []
    values: dict[str, str] = {}
    seen: dict[str, int] = {}

    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        problems.append("File starts with a UTF-8 BOM — the first key may be silently mangled.")
        raw = raw[3:]
    if b"\r\n" in raw:
        problems.append("CRLF (Windows) line endings found — values may carry an invisible \\r.")
    if raw and not raw.endswith(b"\n"):
        problems.append(
            "File does NOT end with a newline — any line appended with '>>' will "
            "CONCATENATE onto the last key and both variables are lost."
        )

    text = raw.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    in_multiline_quote: str | None = None
    multiline_start = 0

    for idx, line in enumerate(lines, start=1):
        if in_multiline_quote:
            if in_multiline_quote in line:
                in_multiline_quote = None
            continue
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export "):
            stripped = stripped[len("export "):]
        if "=" not in stripped:
            problems.append(f"Line {idx}: no '=' — line is ignored by the parser: {stripped[:60]!r}")
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        if key != stripped.partition("=")[0]:
            problems.append(f"Line {idx}: whitespace around the key '{key}' — some parsers DROP this line.")
        if not KEY_RE.match(key):
            problems.append(f"Line {idx}: invalid key name {key!r} — line is dropped. "
                            "If it looks like TWO keys glued together, a newline is missing above it.")
            continue
        if key in seen:
            problems.append(f"Line {idx}: duplicate key {key} (first at line {seen[key]}) — the LAST one wins.")
        seen[key] = idx

        value = value.strip()
        _known = OTP_KEYS + ["DATABASE_URL", "REDIS_URL", "JWT_SECRET", "DISABLE_SCHEDULER"]
        if any(f"{k}=" in value for k in _known):
            problems.append(
                f"Line {idx}: value of {key} CONTAINS another key=value "
                f"(missing newline when the line was appended?): {value[:60]!r}"
            )
        if value[:1] in ("'", '"'):
            quote = value[0]
            if len(value) == 1 or not value.rstrip().endswith(quote) or value.rstrip() == quote:
                problems.append(
                    f"Line {idx}: UNBALANCED {quote} quote on {key} — every line below it is "
                    "SWALLOWED into this value until the next matching quote. "
                    "This is the classic way OTP_MODE 'disappears' from the container."
                )
                in_multiline_quote = quote
                multiline_start = idx
                continue
            value = value.rstrip()[1:-1]
        else:
            m = re.search(r"\s+#", value)
            if m:
                problems.append(f"Line {idx}: inline comment on {key} — stripped by compose, "
                                "but kept verbatim by docker run --env-file. Avoid.")
                value = value[:m.start()].strip()
        if "\u201c" in value or "\u201d" in value or "\u2018" in value:
            problems.append(f"Line {idx}: SMART QUOTES in {key} — replace with plain ' or \".")
        values[key] = value

    if in_multiline_quote:
        problems.append(
            f"UNBALANCED quote opened at line {multiline_start} never closes — everything "
            "after it (including any OTP_* lines) never becomes an environment variable."
        )

    print(f"== .env lint: {path} ({len(lines)} lines, {len(values)} variables parsed) ==")
    if problems:
        for p in problems:
            print(f"  [WARN] {p}")
    else:
        print("  OK — no parse hazards detected.")
    return values


def show_otp_config(values: dict[str, str]) -> None:
    print("\n== Effective OTP configuration (from this .env) ==")
    for key in OTP_KEYS:
        v = values.get(key)
        if v is None:
            print(f"  {key:34s} = (MISSING)")
        elif key == "SMSGATEWAYHUB_API_KEY":
            print(f"  {key:34s} = {mask(v)}")
        else:
            print(f"  {key:34s} = {v!r}")
    mode = (values.get("OTP_MODE") or "").lower()
    if mode != "smsgatewayhub":
        print(f"\n  [WARN] OTP_MODE={mode!r} — real SMS will NOT be sent by the app.")
    if not values.get("SMSGATEWAYHUB_ENTITY_ID"):
        print("  [WARN] SMSGATEWAYHUB_ENTITY_ID is blank — SMSGatewayHub requires EntityId "
              "(DLT PE ID) for India DLT traffic; sends may be rejected/dropped.")


def send_test_sms(values: dict[str, str], phone: str) -> int:
    for key in ("SMSGATEWAYHUB_API_KEY", "SMSGATEWAYHUB_SENDER_ID",
                "SMSGATEWAYHUB_DLT_TEMPLATE_ID", "OTP_TEMPLATE_TEXT"):
        if not values.get(key):
            print(f"\n[ABORT] cannot send: {key} is missing/empty in the .env")
            return 2
    otp = f"{random.randrange(10**6):06d}"
    text = values["OTP_TEMPLATE_TEXT"].replace("{#var#}", otp, 1).replace("{#var#}", "5", 1)
    params = {
        "APIKey": values["SMSGATEWAYHUB_API_KEY"],
        "senderid": values["SMSGATEWAYHUB_SENDER_ID"],
        "channel": "2",
        "DCS": "0",
        "flashsms": "0",
        "number": phone.lstrip("+"),
        "text": text,
        "route": "1",
        "dlttemplateid": values["SMSGATEWAYHUB_DLT_TEMPLATE_ID"],
    }
    if values.get("SMSGATEWAYHUB_ENTITY_ID"):
        params["EntityId"] = values["SMSGATEWAYHUB_ENTITY_ID"]

    print(f"\n== Sending REAL test SMS to {phone} (OTP {otp}) ==")
    print(f"  senderid={params['senderid']} dlttemplateid={params['dlttemplateid']} "
          f"EntityId={params.get('EntityId', '(not sent)')} APIKey={mask(params['APIKey'])}")
    url = SMSGATEWAYHUB_URL + "?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=20) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            print(f"  RAW HTTP status : {resp.status}")
            print(f"  RAW response    : {body}")
            ok = '"ErrorCode":"000"' in body.replace(" ", "") or '"ErrorCode":"0"' in body.replace(" ", "")
            print(f"  VERDICT         : {'ACCEPTED by gateway — check the handset' if ok else 'REJECTED — see ErrorMessage above'}")
            return 0 if ok else 1
    except urllib.error.HTTPError as e:
        print(f"  RAW HTTP status : {e.code}")
        print(f"  RAW response    : {(e.read() or b'').decode('utf-8', errors='replace')[:500]}")
        return 1
    except Exception as e:
        print(f"  NETWORK FAILURE : {type(e).__name__}: {e}")
        return 1


def main() -> int:
    ap = argparse.ArgumentParser(description="SMSGatewayHub / .env diagnostic")
    ap.add_argument("--env-file", default=".env", help="path to the .env file (default ./.env)")
    ap.add_argument("--send", metavar="+91XXXXXXXXXX", help="send ONE real test SMS to this number")
    args = ap.parse_args()

    path = Path(args.env_file)
    if not path.exists():
        print(f"[ABORT] {path} not found — run from /opt/hogoplus or pass --env-file")
        return 2

    values = lint_and_parse(path)
    show_otp_config(values)

    print("\n== Compare against the RUNNING container ==")
    print("  docker compose exec backend printenv | grep -E 'OTP_|SMSGATEWAYHUB_|DEMO_' | sed 's/API_KEY=.*/API_KEY=****/'")
    print("  docker compose logs backend | grep 'OTP CONFIG'   # boot line shows the effective config")

    if args.send:
        if not re.match(r"^\+91[6-9]\d{9}$", args.send):
            print(f"[ABORT] {args.send!r} is not a valid +91 number")
            return 2
        return send_test_sms(values, args.send)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BrokenPipeError:  # piping into `head` etc.
        sys.exit(0)
