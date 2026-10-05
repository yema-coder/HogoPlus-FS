#!/usr/bin/env python3
"""Pre-download the number-plate detection + OCR ONNX models at BUILD time.

The production EC2 host has restricted outbound egress, so the models MUST be
baked into the Docker image — never fetched at runtime. This script is run
inside the Docker build (see the repo-root Dockerfile) AFTER the backend code is
copied and the Python deps are installed.

Behaviour:
  * YuNet face model is vendored at ``backend/ml_models/yunet.onnx`` — verified only.
  * The plate detector (open-image-models, YOLOv9) and OCR (fast-plate-ocr, CCT-XS)
    download to ``$HOME/.cache/{open-image-models,fast-plate-ocr}`` on first
    instantiation; that cache becomes part of the image layer.
  * Exits NON-ZERO if any model cannot be obtained, so the build fails loudly
    instead of shipping an image that silently tries (and fails) to download at
    runtime.

Run locally to warm your own cache:  ``python scripts/prefetch_models.py``
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

# Allow running as a bare script (python scripts/prefetch_models.py) by putting
# the backend root (parent of this scripts/ dir) on sys.path so `import app` works.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _size_mb(p: Path) -> str:
    try:
        return f"{p.stat().st_size / (1024 * 1024):.1f} MB"
    except OSError:
        return "?"


def main() -> int:
    # app.vision_local keeps the heavy libs (cv2 / open_image_models /
    # fast_plate_ocr) lazy, so importing it is cheap and config-free.
    from app import vision_local as V

    ok = True

    # 1) YuNet face model — vendored, verify it is present.
    yunet = V._YUNET_PATH
    if yunet.exists():
        print(f"[prefetch] YuNet face model OK: {yunet} ({_size_mb(yunet)})")
    else:
        print(f"[prefetch] ERROR: YuNet face model MISSING at {yunet}")
        ok = False

    # 2) Plate detector (YOLOv9) — instantiation triggers the download.
    t = time.time()
    if V._get_plate_detector() is not None:
        print(f"[prefetch] plate detector OK: {V._PLATE_MODEL} ({time.time() - t:.1f}s)")
    else:
        print(f"[prefetch] ERROR: plate detector FAILED to load: {V._PLATE_MODEL}")
        ok = False

    # 3) Plate OCR (CCT-XS) — instantiation triggers the download.
    t = time.time()
    if V._get_plate_ocr() is not None:
        print(f"[prefetch] plate OCR OK: {V._OCR_MODEL} ({time.time() - t:.1f}s)")
    else:
        print(f"[prefetch] ERROR: plate OCR FAILED to load: {V._OCR_MODEL}")
        ok = False

    # 4) Report what landed in the cache (now baked into the image layer).
    cache = Path.home() / ".cache"
    for sub in ("open-image-models", "fast-plate-ocr"):
        for onnx in sorted((cache / sub).rglob("*.onnx")):
            print(f"[prefetch] cached: {onnx} ({_size_mb(onnx)})")

    print("[prefetch] DONE — all models present" if ok else "[prefetch] INCOMPLETE — see errors above")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
