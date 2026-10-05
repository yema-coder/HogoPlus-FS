"""Step 5 — plate-scale cross-check.

A standard number plate has a known real-world width. From a detected plate's
apparent width (as a fraction of the image width) we can estimate the camera→plate
distance independently of the AR sensor, and flag whether the two agree.

Geometry (pinhole):  distance = f_px · W_real / plate_width_px
With plate_width_px = w_frac · image_width_px and k ≡ f_px / image_width_px
(a single per-camera constant, resolution-independent, ~1.0–1.4 for phones):

    distance ≈ k · W_real / w_frac

Calibration derives k from one trusted capture (known AR distance + plate):

    k = ar_distance · w_frac / W_real
"""
from __future__ import annotations

CONSISTENCY_TOLERANCE_PCT = 33.0  # AR vs plate-scale within ±33% ⇒ "consistent"


def estimate_distance(k: float, ref_width_m: float, plate_w_frac: float) -> float | None:
    if not plate_w_frac or plate_w_frac <= 0 or not k or not ref_width_m:
        return None
    return round(k * ref_width_m / plate_w_frac, 2)


def compute_plate_scale(
    *, enabled: bool, k: float, ref_width_m: float,
    plate_w_frac: float | None, ar_distance_m: float | None,
) -> dict | None:
    """Return the cross-check block for the analysis API, or None when it can't run."""
    if not enabled or not plate_w_frac:
        return None
    est = estimate_distance(k, ref_width_m, plate_w_frac)
    if est is None:
        return None
    out: dict = {"est_distance_m": est, "ref_width_m": ref_width_m, "k": round(k, 3)}
    if ar_distance_m and ar_distance_m > 0:
        delta_pct = round(abs(est - ar_distance_m) / ar_distance_m * 100, 1)
        out["ar_distance_m"] = ar_distance_m
        out["delta_pct"] = delta_pct
        out["consistent"] = delta_pct <= CONSISTENCY_TOLERANCE_PCT
    return out


def calibrate_k(*, ar_distance_m: float, plate_w_frac: float, ref_width_m: float) -> float:
    """k from a trusted (distance, plate-width-fraction) pair."""
    if plate_w_frac <= 0 or ref_width_m <= 0:
        raise ValueError("plate width / reference width must be positive")
    return round(ar_distance_m * plate_w_frac / ref_width_m, 4)
