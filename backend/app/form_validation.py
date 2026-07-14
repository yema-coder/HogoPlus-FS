import re
from datetime import datetime


def validate_submission(data: dict, schema: dict) -> list[str]:
    """Validate data_json against a form definition's schema_json. Returns error list."""
    errors: list[str] = []
    fields = schema.get("fields", [])
    known_keys = {f["key"] for f in fields}

    for f in fields:
        key = f["key"]
        ftype = f.get("type", "text")
        required = bool(f.get("required", False))
        rules = f.get("validation") or {}
        val = data.get(key)

        if val is None or (isinstance(val, str) and val.strip() == ""):
            if required:
                errors.append(f"{key}: required")
            continue

        if ftype == "text":
            if not isinstance(val, str):
                errors.append(f"{key}: must be text")
                continue
            regex = rules.get("regex")
            if regex and not re.match(regex, val):
                errors.append(f"{key}: invalid format")
        elif ftype == "number":
            if isinstance(val, bool) or not isinstance(val, (int, float)):
                errors.append(f"{key}: must be a number")
                continue
            if rules.get("min") is not None and val < rules["min"]:
                errors.append(f"{key}: below minimum {rules['min']}")
            if rules.get("max") is not None and val > rules["max"]:
                errors.append(f"{key}: above maximum {rules['max']}")
        elif ftype == "select":
            options = f.get("options") or []
            if val not in options:
                errors.append(f"{key}: invalid option")
        elif ftype == "toggle":
            if not isinstance(val, bool):
                errors.append(f"{key}: must be true/false")
        elif ftype == "datetime":
            try:
                datetime.fromisoformat(str(val).replace("Z", "+00:00"))
            except ValueError:
                errors.append(f"{key}: invalid datetime")
        elif ftype in ("photo", "voice_note"):
            if not isinstance(val, str) or not val:
                errors.append(f"{key}: must be a file key")
        elif ftype == "gps_point":
            ok = (
                isinstance(val, dict)
                and isinstance(val.get("lat"), (int, float))
                and isinstance(val.get("lng"), (int, float))
                and not isinstance(val.get("lat"), bool)
                and not isinstance(val.get("lng"), bool)
            )
            if not ok:
                errors.append(f"{key}: must be {{lat, lng}}")

    unknown = sorted(set(data.keys()) - known_keys)
    if unknown:
        errors.append(f"unknown fields: {', '.join(unknown)}")
    return errors
