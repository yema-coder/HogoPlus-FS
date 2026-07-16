"""Opportunistic ANPR core: Rekognition DetectText first, Universal-Key vision
fallback, OCR-confusable normalization + Indian plate validation.

Shared by the Celery task AND the in-process FastAPI background task (production
containers run no Celery worker, so incident AI executes in the API process).
"""
import logging
import re

logger = logging.getLogger("hogo.anpr")

# Standard Indian registration format: SS RR L(1-3) NNNN (BH series excluded).
INDIAN_STATE_CODES = {
    "AN", "AP", "AR", "AS", "BR", "CG", "CH", "DD", "DL", "DN", "GA", "GJ",
    "HP", "HR", "JH", "JK", "KA", "KL", "LA", "LD", "MH", "ML", "MN", "MP",
    "MZ", "NL", "OD", "OR", "PB", "PY", "RJ", "SK", "TN", "TR", "TS",
    "UK", "UA", "UP", "WB",
}

# OCR confusables — coercion is POSITIONAL: applied only where the plate
# structure demands that character class (e.g. "MHO2FX2660" → "MH02FX2660").
TO_DIGIT = {"O": "0", "Q": "0", "D": "0", "I": "1", "L": "1", "Z": "2", "S": "5", "B": "8", "G": "6"}
TO_ALPHA = {"0": "O", "1": "I", "2": "Z", "5": "S", "8": "B", "6": "G", "4": "A"}

LOOSE_PLATE_RE = re.compile(r"([A-Z]{2})[\s.-]?(\d{1,2})[\s.-]?([A-Z]{1,3})[\s.-]?(\d{4})")


def _coerce(seg: str, want: str) -> str | None:
    out = []
    for ch in seg:
        if want == "digit":
            if ch.isdigit():
                out.append(ch)
            elif ch in TO_DIGIT:
                out.append(TO_DIGIT[ch])
            else:
                return None
        else:
            if ch.isalpha():
                out.append(ch)
            elif ch in TO_ALPHA:
                out.append(TO_ALPHA[ch])
            else:
                return None
    return "".join(out)


def normalize_plate(token: str) -> str | None:
    """Coerce a raw OCR token into a valid Indian plate, or None.
    Handles confusables by position and validates the state code."""
    s = re.sub(r"[^A-Z0-9]", "", token.upper())
    if not 8 <= len(s) <= 11:
        return None
    n = len(s)
    for rto_len in (2, 1):
        for series_len in (3, 2, 1):
            if 2 + rto_len + series_len + 4 != n:
                continue
            state = _coerce(s[0:2], "alpha")
            rto = _coerce(s[2 : 2 + rto_len], "digit")
            series = _coerce(s[2 + rto_len : 2 + rto_len + series_len], "alpha")
            num = _coerce(s[n - 4 :], "digit")
            if None in (state, rto, series, num):
                continue
            if state not in INDIAN_STATE_CODES:
                continue
            return f"{state}{rto}{series}{num}"
    return None


def extract_plate_from_lines(lines: list) -> tuple[str | None, float | None]:
    """Best plate from DetectText LINE results ([{text, confidence}] or plain strings).
    Exact regex hits win over confusable-coerced ones; ties broken by OCR confidence."""
    exact: list[tuple[float, str]] = []
    coerced: list[tuple[float, str]] = []
    for line in lines:
        text = line["text"] if isinstance(line, dict) else str(line)
        conf = float(line.get("confidence", 0.0)) if isinstance(line, dict) else 0.0
        up = text.upper()
        m = LOOSE_PLATE_RE.search(up)
        if m and m.group(1) in INDIAN_STATE_CODES:
            exact.append((conf, "".join(m.groups())))
            continue
        for cand in [re.sub(r"[^A-Z0-9]", "", up), *up.split()]:
            p = normalize_plate(cand)
            if p:
                coerced.append((conf, p))
                break
    if exact:
        conf, plate = max(exact)
        return plate, conf
    if coerced:
        conf, plate = max(coerced)
        return plate, conf
    return None, None


def extract_plate(lines: list) -> str | None:
    """Back-compat helper: plate only (used by form-submission path + older tests)."""
    return extract_plate_from_lines(lines)[0]


VISION_PROMPT = (
    "Look carefully for a vehicle registration number plate (Indian format, e.g. MH02FX2660) "
    "anywhere in this photo. Read the characters exactly as printed. "
    'Respond ONLY with JSON: {"plate": "<characters you read>" or null if no plate is visible, '
    '"confidence": <0-100 integer, how sure you are>}'
)


async def llm_plate_fallback(image_bytes: bytes) -> tuple[str | None, float | None]:
    """Universal-Key vision fallback when DetectText finds no valid plate.
    Returns (normalized plate, confidence 0-100) — plate is None when nothing valid."""
    from app.ai_core import vision_json

    data = await vision_json(VISION_PROMPT, image_bytes)
    raw = data.get("plate")
    if not raw:
        return None, None
    plate = normalize_plate(str(raw))
    if plate is None:
        m = LOOSE_PLATE_RE.search(str(raw).upper())
        if m and m.group(1) in INDIAN_STATE_CODES:
            plate = "".join(m.groups())
    conf = data.get("confidence")
    try:
        conf = float(conf) if conf is not None else None
    except (TypeError, ValueError):
        conf = None
    return plate, conf
