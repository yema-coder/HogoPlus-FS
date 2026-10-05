"""On-device/on-server local computer-vision analysis (Step 3).

Two independent, CPU-only ONNX pipelines that run entirely in-process (no external
API, no torch):

  * FACE DETECTION — OpenCV YuNet (`cv2.FaceDetectorYN`, model bundled at
    ``ml_models/yunet.onnx``). Returns face boxes + a score. We NEVER identify a
    person — only count/locate faces so a reviewer can blur or verify them.
  * NUMBER-PLATE DETECTION + OCR — ``open-image-models`` YOLO-v9 plate detector
    crops each plate, then ``fast-plate-ocr`` reads the characters. Returns plate
    boxes + text + confidence.

All boxes are returned as FRACTIONS (0..1) of the image so the mobile/web client
can overlay them at any display size. Every entry point is defensive: a missing
model, a corrupt image or an inference failure degrades to an empty result and is
logged — it must NEVER raise into the request/background path.

Models are lazy singletons (loaded on first use) and can be released to reclaim
RSS on small containers, mirroring ``app.embeddings.release_model``.
"""
from __future__ import annotations

import ctypes
import gc
import logging
import threading
from pathlib import Path

logger = logging.getLogger("hogo.vision")

# ---- tunables --------------------------------------------------------------
_MAX_SIDE = 1280          # downscale the longest side before inference (speed)
_MAX_FACES = 25
_MAX_PLATES = 10
_FACE_SCORE_THRESH = 0.6
_FACE_NMS_THRESH = 0.3
_PLATE_DET_CONF = 0.4
_PLATE_MODEL = "yolo-v9-t-384-license-plate-end2end"
_OCR_MODEL = "cct-xs-v2-global-model"
_PROVIDERS = ["CPUExecutionProvider"]

_YUNET_PATH = Path(__file__).resolve().parent.parent / "ml_models" / "yunet.onnx"

_lock = threading.Lock()
_face_detector = None  # cv2.FaceDetectorYN
_plate_detector = None  # open_image_models detector
_plate_ocr = None  # fast_plate_ocr.LicensePlateRecognizer


# ---- lazy loaders (each isolated so one missing lib never kills the other) --

def _get_cv2():
    import cv2  # noqa: PLC0415 — heavy import, keep lazy

    return cv2


def _get_face_detector():
    global _face_detector
    if _face_detector is not None:
        return _face_detector
    try:
        cv2 = _get_cv2()
        if not _YUNET_PATH.exists():
            logger.warning("vision: YuNet model missing at %s", _YUNET_PATH)
            return None
        _face_detector = cv2.FaceDetectorYN.create(
            str(_YUNET_PATH), "", (320, 320), _FACE_SCORE_THRESH, _FACE_NMS_THRESH, 5000
        )
    except Exception:
        logger.exception("vision: failed to load YuNet face detector")
        _face_detector = None
    return _face_detector


def _get_plate_detector():
    global _plate_detector
    if _plate_detector is not None:
        return _plate_detector
    try:
        from open_image_models import create_detector  # noqa: PLC0415

        _plate_detector = create_detector(
            _PLATE_MODEL, conf_thresh=_PLATE_DET_CONF, providers=_PROVIDERS
        )
    except Exception:
        logger.exception("vision: failed to load plate detector (%s)", _PLATE_MODEL)
        _plate_detector = None
    return _plate_detector


def _get_plate_ocr():
    global _plate_ocr
    if _plate_ocr is not None:
        return _plate_ocr
    try:
        from fast_plate_ocr import LicensePlateRecognizer  # noqa: PLC0415

        _plate_ocr = LicensePlateRecognizer(_OCR_MODEL, device="cpu", providers=_PROVIDERS)
    except Exception:
        logger.exception("vision: failed to load plate OCR (%s)", _OCR_MODEL)
        _plate_ocr = None
    return _plate_ocr


def release_models() -> None:
    """Drop every loaded model and return RSS to the OS (small-container hygiene)."""
    global _face_detector, _plate_detector, _plate_ocr
    with _lock:
        _face_detector = None
        _plate_detector = None
        _plate_ocr = None
    gc.collect()
    try:
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except Exception:
        pass


def models_available() -> dict:
    """Cheap health probe used by the admin diagnostics (loads lazily)."""
    with _lock:
        return {
            "faces": _get_face_detector() is not None,
            "plates": _get_plate_detector() is not None,
            "ocr": _get_plate_ocr() is not None,
        }


# ---- helpers ---------------------------------------------------------------

def _decode_and_scale(img_bytes: bytes):
    """bytes → (bgr_ndarray, scale) downscaled so the longest side ≤ _MAX_SIDE."""
    import cv2  # noqa: PLC0415
    import numpy as np  # noqa: PLC0415

    arr = np.frombuffer(img_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        return None
    h, w = img.shape[:2]
    longest = max(h, w)
    if longest > _MAX_SIDE:
        s = _MAX_SIDE / float(longest)
        img = cv2.resize(img, (int(round(w * s)), int(round(h * s))), interpolation=cv2.INTER_AREA)
    return img


def _detect_faces(img) -> list[dict]:
    det = _get_face_detector()
    if det is None:
        return None  # signal "unavailable" (vs. [] = ran, found none)
    try:
        h, w = img.shape[:2]
        det.setInputSize((w, h))
        _, faces = det.detect(img)
        out: list[dict] = []
        if faces is not None:
            for f in faces:
                x, y, bw, bh = float(f[0]), float(f[1]), float(f[2]), float(f[3])
                score = float(f[-1])
                out.append(
                    {
                        "x": max(0.0, x / w),
                        "y": max(0.0, y / h),
                        "w": max(0.0, min(1.0, bw / w)),
                        "h": max(0.0, min(1.0, bh / h)),
                        "score": round(score, 3),
                    }
                )
        out.sort(key=lambda d: d["score"], reverse=True)
        return out[:_MAX_FACES]
    except Exception:
        logger.exception("vision: face detection failed")
        return None


def _mean_conf(char_probs) -> float | None:
    try:
        vals = [float(p) for p in list(char_probs) if p is not None]
        if not vals:
            return None
        return round(sum(vals) / len(vals), 3)
    except Exception:
        return None


def _read_plate(ocr, crop) -> tuple[str | None, float | None, str | None]:
    try:
        preds = ocr.run(crop, return_confidence=True)
        if not preds:
            return None, None, None
        p = preds[0]
        text = (getattr(p, "plate", "") or "").strip().upper()
        if not text:
            return None, None, None
        return text, _mean_conf(getattr(p, "char_probs", None)), getattr(p, "region", None)
    except Exception:
        logger.exception("vision: plate OCR failed")
        return None, None, None


def _detect_plates(img) -> list[dict]:
    det = _get_plate_detector()
    ocr = _get_plate_ocr()
    if det is None or ocr is None:
        return None
    try:
        h, w = img.shape[:2]
        results = det.predict(img)
        # a single image yields list[DetectionResult]
        if results and isinstance(results[0], list):
            results = results[0]
        out: list[dict] = []
        for r in results or []:
            bb = r.bounding_box
            x1 = max(0, int(bb.x1))
            y1 = max(0, int(bb.y1))
            x2 = min(w, int(bb.x2))
            y2 = min(h, int(bb.y2))
            if x2 <= x1 or y2 <= y1:
                continue
            crop = img[y1:y2, x1:x2]
            text, ocr_conf, region = _read_plate(ocr, crop)
            det_conf = round(float(getattr(r, "confidence", 0.0)), 3)
            out.append(
                {
                    "x": x1 / w,
                    "y": y1 / h,
                    "w": (x2 - x1) / w,
                    "h": (y2 - y1) / h,
                    "text": text,
                    "det_confidence": det_conf,
                    "ocr_confidence": ocr_conf,
                    "region": region,
                }
            )
        # strongest detections first
        out.sort(key=lambda d: d.get("det_confidence") or 0.0, reverse=True)
        return out[:_MAX_PLATES]
    except Exception:
        logger.exception("vision: plate detection failed")
        return None


# ---- public entry point -----------------------------------------------------

def analyze_image(img_bytes: bytes, *, do_faces: bool = True, do_plates: bool = True) -> dict:
    """Run the requested local pipelines on one image. Never raises.

    Returns ``{"ok", "faces": [...]|None, "plates": [...]|None}`` where a value of
    ``None`` means that pipeline could not run (model unavailable / decode failed)
    and ``[]`` means it ran and found nothing.
    """
    result: dict = {"ok": False, "faces": None, "plates": None}
    try:
        img = _decode_and_scale(img_bytes)
    except Exception:
        logger.exception("vision: image decode failed")
        img = None
    if img is None:
        return result
    with _lock:
        if do_faces:
            result["faces"] = _detect_faces(img)
        if do_plates:
            result["plates"] = _detect_plates(img)
    result["ok"] = True
    return result
