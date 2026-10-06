"""Boxes detected in a rotated image must map back onto the ORIGINAL frame.

Pure geometry, no cv2 and no database — the same class of bug that put the AR
crosshair below the finger, so it gets its own round-trip proof.
"""
from app.vision_local import map_box_from_rotated


def rotate_box_forward(box: dict, rotation: int) -> dict:
    """Where a box in the ORIGINAL lands after rotating the image clockwise.
    Independent implementation — if it and map_box_from_rotated agree on a
    round trip, both describe the same rotation."""
    x, y, w, h = box["x"], box["y"], box["w"], box["h"]
    r = rotation % 360
    if r == 0:
        return dict(box)
    if r == 90:  # u' = 1 - v, v' = u
        return {**box, "x": 1.0 - y - h, "y": x, "w": h, "h": w}
    if r == 180:
        return {**box, "x": 1.0 - x - w, "y": 1.0 - y - h, "w": w, "h": h}
    if r == 270:  # u' = v, v' = 1 - u
        return {**box, "x": y, "y": 1.0 - x - w, "w": h, "h": w}
    raise ValueError(rotation)


BOXES = [
    {"x": 0.10, "y": 0.20, "w": 0.30, "h": 0.40, "score": 0.9},
    {"x": 0.00, "y": 0.00, "w": 1.00, "h": 1.00},          # whole frame
    {"x": 0.70, "y": 0.05, "w": 0.25, "h": 0.15},          # top-right sliver
    {"x": 0.31, "y": 0.34, "w": 0.39, "h": 0.31},          # the real selfie box
]


def _close(a, b, eps=1e-9):
    return all(abs(a[k] - b[k]) < eps for k in ("x", "y", "w", "h"))


def test_round_trip_every_rotation():
    for box in BOXES:
        for rot in (0, 90, 180, 270):
            rotated = rotate_box_forward(box, rot)
            back = map_box_from_rotated(rotated, rot)
            assert _close(back, box), f"rot={rot} box={box} -> {rotated} -> {back}"


def test_width_and_height_swap_on_quarter_turns():
    box = {"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4}
    for rot in (90, 270):
        out = map_box_from_rotated(box, rot)
        assert out["w"] == box["h"] and out["h"] == box["w"]
    for rot in (0, 180):
        out = map_box_from_rotated(box, rot)
        assert out["w"] == box["w"] and out["h"] == box["h"]


def test_known_values():
    # a box hugging the TOP-LEFT of an image rotated 90° CW came from the
    # BOTTOM-LEFT of the original
    out = map_box_from_rotated({"x": 0.0, "y": 0.0, "w": 0.2, "h": 0.1}, 90)
    assert _close(out, {"x": 0.0, "y": 0.8, "w": 0.1, "h": 0.2})
    # and for 270° CW it came from the TOP-RIGHT
    out = map_box_from_rotated({"x": 0.0, "y": 0.0, "w": 0.2, "h": 0.1}, 270)
    assert _close(out, {"x": 0.9, "y": 0.0, "w": 0.1, "h": 0.2})


def test_stays_inside_the_frame_and_keeps_other_fields():
    for box in BOXES:
        for rot in (0, 90, 180, 270):
            out = map_box_from_rotated(box, rot)
            assert -1e-9 <= out["x"] <= 1.0 + 1e-9
            assert -1e-9 <= out["y"] <= 1.0 + 1e-9
            assert out["x"] + out["w"] <= 1.0 + 1e-9
            assert out["y"] + out["h"] <= 1.0 + 1e-9
    scored = map_box_from_rotated({"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2, "score": 0.77}, 90)
    assert scored["score"] == 0.77


def test_zero_and_unknown_rotation_are_identity():
    box = {"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4}
    assert map_box_from_rotated(box, 0) is box
    assert map_box_from_rotated(box, 360) is box
    assert _close(map_box_from_rotated(box, 45), box)
