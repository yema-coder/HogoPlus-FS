#!/usr/bin/env python3
"""Offline accuracy bench for the local camera-AI pipeline (faces + number plates).

Runs the EXACT server pipeline (``app.vision_local.analyze_image``) over a folder
of photos, writes a per-plate CSV plus eyeball-able crops, and prints a summary.

It is deliberately standalone:
  * imports ONLY ``app.vision_local`` and ``app.anpr`` — never ``app.config``,
    ``app.database``, ``app.models`` or ``app.storage``;
  * touches NO database, NO object storage and NO network (apart from the ONNX
    model download that ``open-image-models`` / ``fast-plate-ocr`` perform on a
    cold cache — inside the production image that cache is already baked in);
  * CPU-only (``vision_local`` pins ``CPUExecutionProvider``);
  * a failure on one image is recorded in its row and never aborts the run.

Usage
-----
    python scripts/plate_face_bench.py <folder> [--out DIR] [--recursive]
                                       [--limit N] [--no-faces] [--no-plates]
                                       [--threads N] [--no-crops]

See ``scripts/BENCH_README.md`` for copy-pasteable run commands.
"""
from __future__ import annotations

import argparse
import csv
import statistics
import sys
import threading
import time
import traceback
from pathlib import Path

# Allow running as a bare script (``python scripts/plate_face_bench.py``) by
# putting the backend root (parent of this scripts/ dir) on sys.path so that
# ``import app`` resolves. Mirrors scripts/prefetch_models.py.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp")

#: Fallback tier label when the pipeline does not report a ``source`` itself.
DEFAULT_SOURCE_TIER = "local:yolov9-t+cct-xs"

CSV_COLUMNS = [
    "image_index",      # 0-based position in the sorted file list
    "filename",         # basename
    "relpath",          # path relative to the scanned folder (useful with --recursive)
    "width",            # ORIGINAL image width in px (0 if it could not be decoded)
    "height",           # ORIGINAL image height in px
    "row_kind",         # "image" (no plate on this row) | "plate" (one plate per row)
    "plate_index",      # 1..N for row_kind=plate, blank for row_kind=image
    "faces_found",      # per-image face count
    "face_scores",      # semicolon-joined YuNet scores, 3dp
    "plates_found",     # per-image plate count
    "raw_ocr",          # verbatim OCR text for THIS plate
    "normalised_plate", # app.anpr normaliser output, or blank if it did not validate
    "det_confidence",   # YOLOv9 plate-box confidence, 3dp
    "ocr_confidence",   # mean per-character OCR confidence, 3dp
    "source_tier",      # which engine produced this plate
    "region",           # region/plate-layout hint from the OCR model, if any
    "plate_format",     # standard | bh — layout the normaliser matched (if it reports one)
    "plate_state",      # state code the normaliser validated (standard format only)
    "normalise_fixes",  # confusable repairs the normaliser had to apply, e.g. "pos2 O->0"
    "faces_status",     # ok | unavailable (model missing) | no_image | skipped
    "plates_status",    # ok | unavailable (model missing) | no_image | skipped
    "elapsed_ms",       # analyze_image() only — the pipeline cost
    "total_ms",         # incl. this tool's own decode + crop writing
    "is_cold",          # 1 on the first image processed (includes model load)
    "status",           # ok | decode_failed | error
    "error",            # exception text for status=error, else blank
    "crop_stem",        # stem used for this image's crop filenames
    "face_crops",       # semicolon-joined face crop filenames written
    "plate_crop",       # crop filename for THIS plate row
]


# ---------------------------------------------------------------------------
# seams — every heavy / filesystem-touching call goes through one of these so
# the stub tests in scripts/test_bench_tool.py can monkeypatch them.
# ---------------------------------------------------------------------------

def analyze(img_bytes, do_faces=True, do_plates=True):
    """Call the real server pipeline. Imported lazily so --help needs no cv2."""
    from app import vision_local  # noqa: PLC0415 — heavy import, keep lazy

    return vision_local.analyze_image(img_bytes, do_faces=do_faces, do_plates=do_plates)


def decode_image(img_bytes):
    """bytes -> (bgr_ndarray, width, height). Returns (None, 0, 0) on failure.

    NOTE: this is a SECOND decode (``analyze_image`` decodes internally and
    downscales to 1280px for inference). We decode at full size so the crops the
    owner eyeballs come from the ORIGINAL pixels, and so width/height are real.
    """
    try:
        import cv2  # noqa: PLC0415
        import numpy as np  # noqa: PLC0415

        arr = np.frombuffer(img_bytes, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            return None, 0, 0
        h, w = img.shape[:2]
        return img, int(w), int(h)
    except Exception:
        return None, 0, 0


def write_crop(img, rect, dest):
    """Write img[y1:y2, x1:x2] to ``dest`` as JPEG. Returns True on success."""
    try:
        import cv2  # noqa: PLC0415

        x1, y1, x2, y2 = rect
        sub = img[y1:y2, x1:x2]
        dest.parent.mkdir(parents=True, exist_ok=True)
        return bool(cv2.imwrite(str(dest), sub, [int(cv2.IMWRITE_JPEG_QUALITY), 92]))
    except Exception:
        return False


# ---------------------------------------------------------------------------
# plate normaliser — imported DEFENSIVELY. app/anpr.py is being strengthened in
# parallel and may grow a richer helper; prefer it when present, otherwise fall
# back to the known-good normalize_plate(). We never edit anpr.py from here.
# ---------------------------------------------------------------------------

#: Richer helpers we will use if they turn up in app.anpr, best-first.
_PREFERRED_NORMALISERS = (
    "normalize_plate_strict",
    "normalize_plate_v2",
    "normalise_plate",
    "normalize_plate_token",
    "best_plate",
    "canonical_plate",
    "normalize_plate",
)

#: Richer helpers that return a dict with an audit trail, best-first. These give
#: us plate_format / plate_state / normalise_fixes on top of the plate itself.
_PREFERRED_DETAIL_NORMALISERS = (
    "normalize_plate_detail",
    "normalise_plate_detail",
    "normalize_plate_info",
)

#: Keys we will look for inside such a dict (anpr.py is still in flux).
_DETAIL_PLATE_KEYS = ("normalised", "normalized", "plate", "value")

_normaliser_lock = threading.Lock()
_normaliser = None             # resolved string-returning callable
_normaliser_name = None        # its name, for the summary
_detail_normaliser = False     # False = not yet resolved, None = none available
_detail_normaliser_name = None


def _coerce_plate_result(value):
    """Accept str | None | (str, conf) | [str, ...] and return str | None."""
    if value is None:
        return None
    if isinstance(value, (tuple, list)):
        value = value[0] if value else None
        if value is None:
            return None
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _resolve_normaliser():
    """Pick the best available normaliser in app.anpr exactly once."""
    global _normaliser, _normaliser_name
    with _normaliser_lock:
        if _normaliser is not None:
            return _normaliser, _normaliser_name
        try:
            from app import anpr  # noqa: PLC0415 — pure stdlib module
        except Exception:
            _normaliser, _normaliser_name = (lambda _t: None), "unavailable"
            return _normaliser, _normaliser_name
        for name in _PREFERRED_NORMALISERS:
            fn = getattr(anpr, name, None)
            if callable(fn):
                _normaliser, _normaliser_name = fn, name
                return _normaliser, _normaliser_name
        _normaliser, _normaliser_name = (lambda _t: None), "none-found"
        return _normaliser, _normaliser_name


def normalise_plate_text(text):
    """Best-effort Indian-plate normalisation of one raw OCR token."""
    if not text:
        return None
    fn, name = _resolve_normaliser()
    try:
        out = _coerce_plate_result(fn(text))
    except Exception:
        out = None
    if out:
        return out
    # A richer helper may be stricter than the baseline; always give the
    # known-good normalize_plate a turn before giving up.
    if name != "normalize_plate":
        try:
            from app import anpr  # noqa: PLC0415

            base = getattr(anpr, "normalize_plate", None)
            if callable(base):
                return _coerce_plate_result(base(text))
        except Exception:
            return None
    return None


def _resolve_detail_normaliser():
    """Find a dict-returning normaliser in app.anpr, if one exists."""
    global _detail_normaliser, _detail_normaliser_name
    with _normaliser_lock:
        if _detail_normaliser is not False:
            return _detail_normaliser, _detail_normaliser_name
        try:
            from app import anpr  # noqa: PLC0415
        except Exception:
            _detail_normaliser, _detail_normaliser_name = None, None
            return _detail_normaliser, _detail_normaliser_name
        for name in _PREFERRED_DETAIL_NORMALISERS:
            fn = getattr(anpr, name, None)
            if callable(fn):
                _detail_normaliser, _detail_normaliser_name = fn, name
                return _detail_normaliser, _detail_normaliser_name
        _detail_normaliser, _detail_normaliser_name = None, None
        return _detail_normaliser, _detail_normaliser_name


def normalise_plate_info(text):
    """Normalise one raw OCR token and return whatever audit trail is available.

    Always returns a dict with the four keys below; the extras stay blank when
    app.anpr has no dict-returning helper (so the CSV shape never changes).
    """
    info = {"normalised": "", "format": "", "state": "", "fixes": ""}
    if not text:
        return info

    fn, _name = _resolve_detail_normaliser()
    if fn is not None:
        try:
            detail = fn(text)
        except Exception:
            detail = None
        if isinstance(detail, dict):
            for key in _DETAIL_PLATE_KEYS:
                value = detail.get(key)
                if isinstance(value, str) and value.strip():
                    info["normalised"] = value.strip()
                    break
            if info["normalised"]:
                fmt = detail.get("format")
                state = detail.get("state")
                fixes = detail.get("fixes")
                info["format"] = fmt if isinstance(fmt, str) else ""
                info["state"] = state if isinstance(state, str) else ""
                if isinstance(fixes, (list, tuple)):
                    info["fixes"] = ";".join(str(f) for f in fixes)
                elif isinstance(fixes, str):
                    info["fixes"] = fixes
                return info

    # No detail helper, or it declined / returned something unexpected.
    info["normalised"] = normalise_plate_text(text) or ""
    return info


# ---------------------------------------------------------------------------
# pure helpers
# ---------------------------------------------------------------------------

def find_images(folder, recursive=False, limit=None):
    """Deterministic, sorted list of image paths under ``folder``."""
    folder = Path(folder)
    it = folder.rglob("*") if recursive else folder.glob("*")
    found = [
        p for p in it
        if p.is_file() and p.suffix.lower() in IMAGE_EXTS and not p.name.startswith(".")
    ]
    found.sort(key=lambda p: str(p).lower())
    if limit is not None and limit >= 0:
        found = found[:limit]
    return found


def box_to_pixels(box, width, height, margin=0.08, min_margin_px=4):
    """Fractional {x,y,w,h} -> clamped integer (x1, y1, x2, y2), or None.

    Guards against out-of-range / inverted / degenerate boxes: everything is
    clamped into the image and a zero-area result returns None.
    """
    if width <= 0 or height <= 0:
        return None
    try:
        fx = float(box.get("x", 0.0))
        fy = float(box.get("y", 0.0))
        fw = float(box.get("w", 0.0))
        fh = float(box.get("h", 0.0))
    except (AttributeError, TypeError, ValueError):
        return None
    if fw <= 0.0 or fh <= 0.0:
        return None
    x1 = fx * width
    y1 = fy * height
    x2 = (fx + fw) * width
    y2 = (fy + fh) * height
    mx = max(min_margin_px, (x2 - x1) * margin)
    my = max(min_margin_px, (y2 - y1) * margin)
    x1 = int(max(0, round(x1 - mx)))
    y1 = int(max(0, round(y1 - my)))
    x2 = int(min(width, round(x2 + mx)))
    y2 = int(min(height, round(y2 + my)))
    if x2 <= x1 or y2 <= y1:
        return None
    return x1, y1, x2, y2


def _fmt(value, places=3):
    if value is None:
        return ""
    try:
        return "{0:.{1}f}".format(float(value), places)
    except (TypeError, ValueError):
        return ""


def _unique_stem(path, used):
    """Collision-free crop stem (two folders can hold the same filename)."""
    stem = path.stem
    candidate = stem
    n = 1
    while candidate in used:
        n += 1
        candidate = "{0}-{1}".format(stem, n)
    used.add(candidate)
    return candidate


def _blank_row():
    return {col: "" for col in CSV_COLUMNS}


# ---------------------------------------------------------------------------
# per-image work
# ---------------------------------------------------------------------------

def process_image(path, index, root, crops_dir, stem, opts):
    """Run the pipeline on one image. NEVER raises — errors land in the row."""
    base = _blank_row()
    base["image_index"] = index
    base["filename"] = path.name
    try:
        base["relpath"] = str(path.relative_to(root))
    except ValueError:
        base["relpath"] = str(path)
    base["crop_stem"] = stem
    base["is_cold"] = 1 if index == 0 else 0
    base["faces_status"] = "ok" if opts["do_faces"] else "skipped"
    base["plates_status"] = "ok" if opts["do_plates"] else "skipped"

    t_total = time.perf_counter()
    try:
        img_bytes = path.read_bytes()
        img, width, height = decode_image(img_bytes)
        base["width"] = width
        base["height"] = height

        t0 = time.perf_counter()
        result = analyze(img_bytes, do_faces=opts["do_faces"], do_plates=opts["do_plates"])
        base["elapsed_ms"] = round((time.perf_counter() - t0) * 1000.0, 1)

        result = result or {}
        faces = result.get("faces")
        plates = result.get("plates")

        if opts["do_faces"]:
            base["faces_status"] = "unavailable" if faces is None else "ok"
        if opts["do_plates"]:
            base["plates_status"] = "unavailable" if plates is None else "ok"

        faces = faces or []
        plates = plates or []
        base["faces_found"] = len(faces)
        base["plates_found"] = len(plates)
        base["face_scores"] = ";".join(_fmt(f.get("score")) for f in faces)

        if img is None or not result.get("ok", True):
            base["status"] = "decode_failed"
            # The pipeline returns faces/plates=None when the image could not be
            # decoded. That is NOT a missing model, so do not cry "unavailable".
            for key in ("faces_status", "plates_status"):
                if base[key] == "unavailable":
                    base[key] = "no_image"
        else:
            base["status"] = "ok"

        # ---- crops -------------------------------------------------------
        face_crop_names = []
        plate_crop_names = ["" for _ in plates]
        if opts["write_crops"] and img is not None:
            for i, face in enumerate(faces, start=1):
                rect = box_to_pixels(face, width, height, opts["margin"])
                if rect is None:
                    continue
                name = "{0}__face{1}.jpg".format(stem, i)
                if write_crop(img, rect, crops_dir / name):
                    face_crop_names.append(name)
            for i, plate in enumerate(plates, start=1):
                rect = box_to_pixels(plate, width, height, opts["margin"])
                if rect is None:
                    continue
                name = "{0}__plate{1}.jpg".format(stem, i)
                if write_crop(img, rect, crops_dir / name):
                    plate_crop_names[i - 1] = name
        base["face_crops"] = ";".join(face_crop_names)

        # ---- rows: one per plate, or one for the image when there are none
        rows = []
        if plates:
            for i, plate in enumerate(plates, start=1):
                row = dict(base)
                row["row_kind"] = "plate"
                row["plate_index"] = i
                raw = plate.get("text") or ""
                row["raw_ocr"] = raw
                info = normalise_plate_info(raw)
                row["normalised_plate"] = info["normalised"]
                row["plate_format"] = info["format"]
                row["plate_state"] = info["state"]
                row["normalise_fixes"] = info["fixes"]
                row["det_confidence"] = _fmt(plate.get("det_confidence"))
                row["ocr_confidence"] = _fmt(plate.get("ocr_confidence"))
                row["source_tier"] = plate.get("source") or DEFAULT_SOURCE_TIER
                row["region"] = plate.get("region") or ""
                row["plate_crop"] = plate_crop_names[i - 1]
                rows.append(row)
        else:
            base["row_kind"] = "image"
            rows = [base]
    except Exception as exc:  # noqa: BLE001 — one bad image must not stop the run
        base["row_kind"] = "image"
        base["status"] = "error"
        base["error"] = "{0}: {1}".format(type(exc).__name__, exc).replace("\n", " ")[:500]
        if opts["traceback"]:
            sys.stderr.write(
                "[bench] {0} FAILED\n{1}\n".format(path, traceback.format_exc())
            )
        rows = [base]

    total_ms = round((time.perf_counter() - t_total) * 1000.0, 1)
    for row in rows:
        row["total_ms"] = total_ms
    return rows


# ---------------------------------------------------------------------------
# driver
# ---------------------------------------------------------------------------

def run(folder, out_dir, recursive=False, limit=None, do_faces=True, do_plates=True,
        threads=1, write_crops=True, margin=0.08, show_traceback=False, quiet=False):
    """Walk the folder, bench every image, write CSV + crops, return a summary dict."""
    root = Path(folder).resolve()
    if not root.is_dir():
        raise SystemExit("[bench] not a directory: {0}".format(root))

    out = Path(out_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    crops_dir = out / "crops"
    if write_crops:
        crops_dir.mkdir(parents=True, exist_ok=True)

    images = find_images(root, recursive=recursive, limit=limit)
    if not images:
        raise SystemExit(
            "[bench] no {0} files found under {1}{2}".format(
                "/".join(e.lstrip(".") for e in IMAGE_EXTS),
                root,
                "" if recursive else " (try --recursive)",
            )
        )

    opts = {
        "do_faces": do_faces,
        "do_plates": do_plates,
        "write_crops": write_crops,
        "margin": margin,
        "traceback": show_traceback,
    }

    # Stems are assigned up-front, in sorted order, so crop names are identical
    # between runs and independent of thread scheduling.
    used_stems = set()
    jobs = [(i, p, _unique_stem(p, used_stems)) for i, p in enumerate(images)]

    if not quiet:
        print("[bench] {0} image(s) under {1}".format(len(jobs), root))
        print("[bench] faces={0} plates={1} threads={2} crops={3}".format(
            do_faces, do_plates, threads, write_crops))
        print("[bench] image 1 of {0} also pays the model-load cost (cold)…".format(len(jobs)))

    def work(job):
        i, p, stem = job
        return i, process_image(p, i, root, crops_dir, stem, opts)

    collected = {}
    # The first image is ALWAYS run alone: it carries the model-load cost, and
    # keeping it out of the pool keeps the cold/warm split meaningful.
    first_index, first_rows = work(jobs[0])
    collected[first_index] = first_rows
    rest = jobs[1:]
    if rest:
        if threads and threads > 1:
            from concurrent.futures import ThreadPoolExecutor  # noqa: PLC0415

            with ThreadPoolExecutor(max_workers=threads) as pool:
                for i, rows in pool.map(work, rest):
                    collected[i] = rows
        else:
            for job in rest:
                i, rows = work(job)
                collected[i] = rows
                if not quiet and (i + 1) % 25 == 0:
                    print("[bench]   {0}/{1}…".format(i + 1, len(jobs)))

    all_rows = []
    for i in range(len(jobs)):
        all_rows.extend(collected.get(i, []))

    csv_path = out / "results.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(all_rows)

    summary = summarise(all_rows, csv_path, out)
    if not quiet:
        print_summary(summary)
    return summary


def summarise(rows, csv_path, out_dir):
    """Collapse the per-plate rows back to per-image stats."""
    per_image = {}
    for row in rows:
        per_image.setdefault(row["image_index"], row)  # first row carries image-level data

    images = list(per_image.values())
    # Only images the pipeline actually ran on carry a meaningful duration; a
    # decode failure returns in ~0 ms and would wreck the median.
    cold_ms = None
    cold_failed = False
    warm = []
    for row in images:
        ms = row.get("elapsed_ms")
        is_cold = str(row.get("is_cold")) == "1"
        if row.get("status") != "ok" or not isinstance(ms, (int, float)):
            if is_cold:
                cold_failed = True
            continue
        if is_cold:
            cold_ms = ms
        else:
            warm.append(ms)

    def count(pred):
        return sum(1 for r in images if pred(r))

    failures = [
        (r["relpath"], r.get("error") or r.get("status"))
        for r in images if r.get("status") != "ok"
    ]
    normalised = sum(1 for r in rows if r.get("row_kind") == "plate" and r.get("normalised_plate"))
    _, norm_name = _resolve_normaliser()
    _, detail_name = _resolve_detail_normaliser()
    coerced = sum(1 for r in rows
                  if r.get("row_kind") == "plate" and r.get("normalised_plate")
                  and r.get("normalise_fixes"))

    return {
        "csv": str(csv_path),
        "out_dir": str(out_dir),
        "rows": len(rows),
        "images": len(images),
        "images_with_face": count(lambda r: (r.get("faces_found") or 0) >= 1),
        "images_with_plate": count(lambda r: (r.get("plates_found") or 0) >= 1),
        "plate_rows": sum(1 for r in rows if r.get("row_kind") == "plate"),
        "plate_rows_normalised": normalised,
        "faces_unavailable": count(lambda r: r.get("faces_status") == "unavailable"),
        "plates_unavailable": count(lambda r: r.get("plates_status") == "unavailable"),
        "cold_ms": cold_ms,
        "cold_failed": cold_failed,
        "warm_mean_ms": round(statistics.mean(warm), 1) if warm else None,
        "warm_median_ms": round(statistics.median(warm), 1) if warm else None,
        "warm_min_ms": min(warm) if warm else None,
        "warm_max_ms": max(warm) if warm else None,
        "warm_count": len(warm),
        "failures": failures,
        "normaliser": detail_name or norm_name,
        "plate_rows_coerced": coerced,
    }


def print_summary(s):
    def pct(n, d):
        return " ({0:.1f}%)".format(100.0 * n / d) if d else ""

    n = s["images"]
    print("")
    print("================ BENCH SUMMARY ================")
    print("images processed      : {0}  ({1} CSV rows)".format(n, s["rows"]))
    print("images with >=1 face  : {0}{1}".format(s["images_with_face"], pct(s["images_with_face"], n)))
    print("images with >=1 plate : {0}{1}".format(s["images_with_plate"], pct(s["images_with_plate"], n)))
    print("plate rows            : {0}  ({1} normalised to a valid Indian plate)".format(
        s["plate_rows"], s["plate_rows_normalised"]))
    print("plate normaliser used : app.anpr.{0}".format(s["normaliser"]))
    if s.get("plate_rows_coerced"):
        print("  of which {0} only validated after confusable repairs "
              "(see normalise_fixes)".format(s["plate_rows_coerced"]))
    if s["faces_unavailable"]:
        print("!! face pipeline UNAVAILABLE on {0} image(s) — model missing?".format(s["faces_unavailable"]))
    if s["plates_unavailable"]:
        print("!! plate pipeline UNAVAILABLE on {0} image(s) — model missing?".format(s["plates_unavailable"]))
    print("-----------------------------------------------")
    if s["cold_ms"] is None:
        print("cold (image 1, incl. model load) : n/a" + (
            " — image 1 failed, so the model-load cost is folded into a later image"
            if s.get("cold_failed") else ""))
    else:
        print("cold (image 1, incl. model load) : {0} ms".format(s["cold_ms"]))
    if s["warm_count"]:
        print("warm ({0} images)  mean {1} ms | median {2} ms | min {3} | max {4}".format(
            s["warm_count"], s["warm_mean_ms"], s["warm_median_ms"], s["warm_min_ms"], s["warm_max_ms"]))
    else:
        print("warm: n/a (fewer than 2 successful images) — any time above INCLUDES model load")
    print("(timings cover successful images only; failures are excluded)")
    print("-----------------------------------------------")
    if s["failures"]:
        print("failures: {0}".format(len(s["failures"])))
        for rel, err in s["failures"][:20]:
            print("  - {0}: {1}".format(rel, err))
        if len(s["failures"]) > 20:
            print("  … and {0} more (see the status/error columns)".format(len(s["failures"]) - 20))
    else:
        print("failures: 0")
    print("CSV   : {0}".format(s["csv"]))
    print("crops : {0}/crops/".format(s["out_dir"]))
    print("===============================================")


def build_parser():
    p = argparse.ArgumentParser(
        prog="plate_face_bench.py",
        description="Offline accuracy bench for the local face + number-plate pipeline.",
    )
    p.add_argument("folder", help="folder of photos to bench")
    p.add_argument("--out", default="bench-out", help="output directory (default: ./bench-out)")
    p.add_argument("--recursive", action="store_true", help="walk sub-folders too")
    p.add_argument("--limit", type=int, default=None, help="only the first N images (sorted)")
    p.add_argument("--no-faces", action="store_true", help="skip face detection")
    p.add_argument("--no-plates", action="store_true", help="skip plate detection + OCR")
    p.add_argument("--threads", type=int, default=1,
                   help="worker threads (default 1; vision_local serialises inference "
                        "under a global lock, so >1 mainly overlaps disk I/O)")
    p.add_argument("--no-crops", action="store_true", help="do not write crop JPEGs")
    p.add_argument("--crop-margin", type=float, default=0.08,
                   help="extra margin around each crop, as a fraction of the box (default 0.08)")
    p.add_argument("--traceback", action="store_true", help="print a full traceback per failed image")
    p.add_argument("--quiet", action="store_true", help="suppress progress + summary output")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.no_faces and args.no_plates:
        raise SystemExit("[bench] --no-faces and --no-plates together leaves nothing to do")
    summary = run(
        args.folder,
        args.out,
        recursive=args.recursive,
        limit=args.limit,
        do_faces=not args.no_faces,
        do_plates=not args.no_plates,
        threads=max(1, args.threads),
        write_crops=not args.no_crops,
        margin=max(0.0, args.crop_margin),
        show_traceback=args.traceback,
        quiet=args.quiet,
    )
    return 1 if summary["failures"] else 0


if __name__ == "__main__":
    sys.exit(main())
