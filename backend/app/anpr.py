"""Opportunistic ANPR core: Rekognition DetectText first, Universal-Key vision
fallback, OCR-confusable normalization + Indian plate validation.

Shared by the Celery task AND the in-process FastAPI background task (production
containers run no Celery worker, so incident AI executes in the API process).

Dependency-free on purpose (stdlib only, no app.config / app.database imports) so
offline tooling can import it without a database.
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger("hogo.anpr")

# Standard Indian registration format: SS RR L(1-3) NNNN (BH series excluded —
# BH plates are not state-coded and are validated by their own layout below).
INDIAN_STATE_CODES = {
    "AN", "AP", "AR", "AS", "BR", "CG", "CH", "DD", "DL", "DN", "GA", "GJ",
    "HP", "HR", "JH", "JK", "KA", "KL", "LA", "LD", "MH", "ML", "MN", "MP",
    "MZ", "NL", "OD", "OR", "PB", "PY", "RJ", "SK", "TN", "TR", "TS",
    "UK", "UA", "UP", "WB",
}

# OCR confusables — coercion is POSITIONAL: applied only where the plate
# structure demands that character class (e.g. "MHO2FX2660" → "MH02FX2660").
# A character is never coerced in a position where both classes are legal,
# because every supported layout fixes the class of every position.
TO_DIGIT = {"O": "0", "Q": "0", "D": "0", "I": "1", "L": "1", "Z": "2", "S": "5", "B": "8", "G": "6"}
TO_ALPHA = {"0": "O", "1": "I", "2": "Z", "5": "S", "8": "B", "6": "G", "4": "A"}

# Strict (no-confusable) locators used for "the OCR read this exactly right" hits.
LOOSE_PLATE_RE = re.compile(r"([A-Z]{2})[\s.-]?(\d{1,2})[\s.-]?([A-Z]{1,3})[\s.-]?(\d{4})")
BH_PLATE_RE = re.compile(r"(\d{2})[\s.-]?(BH)[\s.-]?(\d{4})[\s.-]?([A-Z]{1,2})")

_NON_ALNUM_RE = re.compile(r"[^A-Z0-9]+")

# A plate candidate is 8-11 alphanumerics; anything else is not a plate.
_MIN_LEN = 8
_MAX_LEN = 11
# A read needing more than this many positional repairs is not trustworthy —
# on a gate log a wrong plate is worse than no plate, so we return None.
_MAX_FIXES = 3
# Token cap for the n-gram scan below (bounds the O(n^2) candidate set on a
# pathologically wordy OCR line); DetectText LINE results are far shorter.
_MAX_TOKENS = 24
# "IND" sticker/hologram text printed to the left of the number on IND plates.
_STICKER_PREFIXES = ("IND",)

# Supported layouts. Each segment is (kind, arg): kind "alpha"/"digit" with a
# length, or "literal" with the exact (letters-only) text required.
#   standard  SS + RTO(1-2 digits) + series(1-3 letters) + 4 digits
#             - 1-letter series covers the older "MH 1 A 1234" shape
#             - 3-letter series covers Delhi-style "DL 8C AF 5030" / "DL 13C AF 5030"
#   bh        Bharat series: YY + "BH" + 4 digits + 1-2 letters (no state code)
# The third element is the maximum number of positional repairs the layout
# tolerates. The 3-letter-series (Delhi-style) layouts get 0: their character
# classes are a superset of the 1-2 letter layouts', so letting them coerce turns
# ordinary text ("DL GATE 1234") and over-long reads ("MH12AB12345") into
# plausible-looking plates. They are accepted only when read exactly.
_LAYOUT_SPECS: tuple[tuple[str, tuple[tuple[str, object], ...], int], ...] = (
    ("standard", (("alpha", 2), ("digit", 2), ("alpha", 2), ("digit", 4)), _MAX_FIXES),  # MH12AB1234
    ("standard", (("alpha", 2), ("digit", 2), ("alpha", 1), ("digit", 4)), _MAX_FIXES),  # MH12A1234
    ("standard", (("alpha", 2), ("digit", 2), ("alpha", 3), ("digit", 4)), 0),           # DL13CAF5030
    ("standard", (("alpha", 2), ("digit", 1), ("alpha", 2), ("digit", 4)), _MAX_FIXES),  # MH1AB1234
    ("standard", (("alpha", 2), ("digit", 1), ("alpha", 1), ("digit", 4)), _MAX_FIXES),  # MH1A1234
    ("standard", (("alpha", 2), ("digit", 1), ("alpha", 3), ("digit", 4)), 0),           # DL8CAF5030
    ("bh", (("digit", 2), ("literal", "BH"), ("digit", 4), ("alpha", 2)), _MAX_FIXES),   # 22BH1234AA
    ("bh", (("digit", 2), ("literal", "BH"), ("digit", 4), ("alpha", 1)), _MAX_FIXES),   # 22BH1234A
)


def _seg_len(kind: str, arg) -> int:
    return len(arg) if kind == "literal" else int(arg)


# (format, segments, total length, max repairs) — total precomputed to skip fast.
_LAYOUTS = tuple(
    (fmt, segs, sum(_seg_len(k, a) for k, a in segs), max_fixes)
    for fmt, segs, max_fixes in _LAYOUT_SPECS
)


def _coerce_class(seg: str, want: str, offset: int) -> tuple[str, list[str]] | None:
    """Coerce `seg` to `want` ("digit" or "alpha") using the confusable maps.
    Returns (coerced text, human-readable fix list) or None if impossible.
    `offset` is the 0-based index of seg within the candidate, for the fix labels."""
    out: list[str] = []
    fixes: list[str] = []
    for i, ch in enumerate(seg):
        if want == "digit":
            if ch.isdigit():
                out.append(ch)
                continue
            rep = TO_DIGIT.get(ch)
        else:
            if ch.isalpha():
                out.append(ch)
                continue
            rep = TO_ALPHA.get(ch)
        if rep is None:
            return None
        out.append(rep)
        fixes.append(f"pos{offset + i} {ch}->{rep}")
    return "".join(out), fixes


def _coerce_literal(seg: str, literal: str, offset: int) -> tuple[str, list[str]] | None:
    res = _coerce_class(seg, "alpha", offset)
    if res is None or res[0] != literal:
        return None
    return res


def _parse_layout(cand: str, segments) -> tuple[str, list[str]] | None:
    """Parse the whole candidate against one layout. Returns (plate, fixes) or None."""
    pos = 0
    out: list[str] = []
    fixes: list[str] = []
    for kind, arg in segments:
        length = _seg_len(kind, arg)
        seg = cand[pos : pos + length]
        if len(seg) != length:
            return None
        res = _coerce_literal(seg, arg, pos) if kind == "literal" else _coerce_class(seg, kind, pos)
        if res is None:
            return None
        out.append(res[0])
        fixes.extend(res[1])
        pos += length
    if pos != len(cand):
        return None
    return "".join(out), fixes


def _candidates(token: str) -> list[str]:
    """Plate-length alphanumeric candidates from a noisy OCR read, best-first.

    Handles missing/extra spaces, dots, hyphens, "IND" sticker prefixes and
    surrounding junk words by trying the whole cleaned string first, then every
    contiguous run of whitespace/punctuation-separated tokens (leftmost-longest)."""
    up = token.upper()
    seen: set[str] = set()
    out: list[str] = []

    def add(c: str) -> None:
        if _MIN_LEN <= len(c) <= _MAX_LEN and c not in seen:
            seen.add(c)
            out.append(c)

    def add_variants(c: str) -> None:
        add(c)
        for pre in _STICKER_PREFIXES:
            if c.startswith(pre):
                add(c[len(pre) :])

    add_variants(_NON_ALNUM_RE.sub("", up))
    tokens = [t for t in _NON_ALNUM_RE.split(up) if t][:_MAX_TOKENS]
    for i in range(len(tokens)):
        for j in range(len(tokens), i, -1):
            add_variants("".join(tokens[i:j]))
    return out


def normalize_plate_detail(token: str | None) -> dict | None:
    """Normalise a raw OCR read into an Indian plate, with a full audit trail.

    Returns None when the read is not a plausible plate (the correct answer for a
    gate log — a confident-looking wrong plate is worse than no plate), else a dict:
        raw        the model's untouched read, exactly as passed in
        candidate  the cleaned alphanumeric substring that was parsed
        normalised the validated plate, e.g. "MH02FX2660"
        format     "standard" | "bh"
        state      state code for "standard", None for "bh"
        fixes      positional confusable repairs applied, e.g. ["pos2 O->0"]
                   (0-based indexes into `candidate` / `normalised`)
    The raw read is never mutated.
    """
    if not token or not isinstance(token, str):
        return None

    # (fix count, candidate rank, layout rank, plate, format, fixes, candidate)
    parses: list[tuple[int, int, int, str, str, list[str], str]] = []
    for ci, cand in enumerate(_candidates(token)):
        for li, (fmt, segs, total, max_fixes) in enumerate(_LAYOUTS):
            if total != len(cand):
                continue
            res = _parse_layout(cand, segs)
            if res is None:
                continue
            plate, fixes = res
            if len(fixes) > max_fixes:
                continue
            if fmt == "standard" and plate[:2] not in INDIAN_STATE_CODES:
                continue
            parses.append((len(fixes), ci, li, plate, fmt, fixes, cand))

    if not parses:
        return None
    parses.sort(key=lambda p: p[:3])
    nfixes, ci, _li, plate, fmt, fixes, cand = parses[0]

    # Reject rather than guess: if a second layout explains the same candidate
    # equally well but yields a different plate, we have no basis to pick one.
    rivals = {p[3] for p in parses if (p[0], p[1]) == (nfixes, ci) and p[3] != plate}
    if rivals:
        logger.debug("ANPR: ambiguous plate read %r → %s", token, sorted({plate, *rivals}))
        return None

    return {
        "raw": token,
        "candidate": cand,
        "normalised": plate,
        "format": fmt,
        "state": plate[:2] if fmt == "standard" else None,
        "fixes": fixes,
    }


def normalize_plate(token: str) -> str | None:
    """Coerce a raw OCR token into a valid Indian plate string, or None.
    Thin wrapper over normalize_plate_detail() for existing callers."""
    detail = normalize_plate_detail(token)
    return detail["normalised"] if detail else None


def _exact_plate_in(up: str) -> str | None:
    """Strict (no confusable coercion) plate hit inside an uppercased OCR line."""
    m = LOOSE_PLATE_RE.search(up)
    if m and m.group(1) in INDIAN_STATE_CODES:
        return "".join(m.groups())
    m = BH_PLATE_RE.search(up)
    if m:
        return "".join(m.groups())
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
        hit = _exact_plate_in(up)
        if hit:
            exact.append((conf, hit))
            continue
        p = normalize_plate(up)
        if p:
            coerced.append((conf, p))
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
    plate = normalize_plate(str(raw)) or _exact_plate_in(str(raw).upper())
    conf = data.get("confidence")
    try:
        conf = float(conf) if conf is not None else None
    except (TypeError, ValueError):
        conf = None
    return plate, conf
