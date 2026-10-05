"""Stub tests for scripts/plate_face_bench.py — no heavy deps, no database.

WHY THIS LIVES IN scripts/ AND NOT IN tests/
--------------------------------------------
``backend/pytest.ini`` sets ``testpaths = tests`` and ``backend/tests/conftest.py``
installs session-scoped autouse fixtures that force a DATABASE_URL and call
``drop_all()`` against a live Postgres. This bench tool must be verifiable on a
laptop with nothing running, so the tests sit next to the script and are invoked
by explicit path.

Run them with:

    python -m pytest backend/scripts/test_bench_tool.py -q

(from the repo root; or ``python -m pytest scripts/test_bench_tool.py -q`` from
``backend/``). Neither cv2, onnxruntime, open-image-models nor Postgres is needed:
the vision call and the JPEG writer are monkeypatched.
"""
from __future__ import annotations

import csv
import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPTS_DIR = Path(__file__).resolve().parent
_BACKEND_DIR = _SCRIPTS_DIR.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))


def _load_bench():
    """Import the script by path (scripts/ is not a package)."""
    spec = importlib.util.spec_from_file_location(
        "plate_face_bench", _SCRIPTS_DIR / "plate_face_bench.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plate_face_bench"] = mod
    spec.loader.exec_module(mod)
    return mod


bench = _load_bench()


# ---------------------------------------------------------------------------
# fixtures / helpers
# ---------------------------------------------------------------------------

class FakeImage:
    """Stand-in for a cv2/numpy BGR array: only slicing is ever used."""

    def __init__(self, w=800, h=600):
        self.w = w
        self.h = h

    def __getitem__(self, key):
        return self


@pytest.fixture(autouse=True)
def _reset_normaliser_cache():
    """The bench resolves app.anpr's normalisers once and caches them globally."""
    def clear():
        bench._normaliser = None
        bench._normaliser_name = None
        bench._detail_normaliser = False   # False = "not yet resolved"
        bench._detail_normaliser_name = None

    clear()
    yield
    clear()


def _make_photos(folder, names):
    folder.mkdir(parents=True, exist_ok=True)
    for name in names:
        (folder / name).write_bytes(b"not-a-real-jpeg")
    return folder


@pytest.fixture
def stub_env(monkeypatch, tmp_path):
    """Patch the three seams: decode_image, write_crop, analyze."""
    written = []

    monkeypatch.setattr(bench, "decode_image", lambda b: (FakeImage(), 800, 600))

    def fake_write_crop(img, rect, dest):
        written.append(Path(dest))
        return True

    monkeypatch.setattr(bench, "write_crop", fake_write_crop)
    return {"written": written, "tmp": tmp_path}


def _read_csv(out_dir):
    with open(Path(out_dir) / "results.csv", newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        return reader.fieldnames, list(reader)


def _box(x=0.1, y=0.1, w=0.2, h=0.2, **extra):
    d = {"x": x, "y": y, "w": w, "h": h}
    d.update(extra)
    return d


# ---------------------------------------------------------------------------
# pure helpers
# ---------------------------------------------------------------------------

def test_find_images_is_sorted_and_filtered(tmp_path):
    folder = _make_photos(tmp_path / "pics", ["b.JPG", "a.png", "c.webp", "notes.txt", ".hidden.jpg"])
    (folder / "sub").mkdir()
    (folder / "sub" / "d.jpeg").write_bytes(b"x")

    flat = bench.find_images(folder)
    assert [p.name for p in flat] == ["a.png", "b.JPG", "c.webp"]

    deep = bench.find_images(folder, recursive=True)
    assert [p.name for p in deep] == ["a.png", "b.JPG", "c.webp", "d.jpeg"]

    assert [p.name for p in bench.find_images(folder, limit=2)] == ["a.png", "b.JPG"]
    # deterministic: a second call gives the identical order
    assert bench.find_images(folder, recursive=True) == deep


@pytest.mark.parametrize(
    "box",
    [
        _box(w=0.0),                 # zero width
        _box(h=-0.5),                # negative height
        {"x": "nope", "y": 0, "w": 0.2, "h": 0.2},   # junk
        _box(x=5.0, y=5.0, w=0.1, h=0.1),            # entirely off-image
    ],
)
def test_box_to_pixels_rejects_bad_boxes(box):
    assert bench.box_to_pixels(box, 800, 600) is None


def test_box_to_pixels_clamps_into_the_image():
    rect = bench.box_to_pixels(_box(x=-0.2, y=-0.2, w=0.5, h=0.5), 800, 600)
    x1, y1, x2, y2 = rect
    assert (x1, y1) == (0, 0)
    assert x2 <= 800 and y2 <= 600
    assert x2 > x1 and y2 > y1

    # margin expands the box but never past the edges
    tight = bench.box_to_pixels(_box(0.4, 0.4, 0.2, 0.2), 800, 600, margin=0.0)
    loose = bench.box_to_pixels(_box(0.4, 0.4, 0.2, 0.2), 800, 600, margin=0.25)
    assert loose[0] < tight[0] and loose[2] > tight[2]


def test_box_to_pixels_needs_real_dimensions():
    assert bench.box_to_pixels(_box(), 0, 0) is None


# ---------------------------------------------------------------------------
# CSV shape
# ---------------------------------------------------------------------------

def test_header_matches_declared_schema(monkeypatch, stub_env, tmp_path):
    folder = _make_photos(tmp_path / "pics", ["one.jpg"])
    monkeypatch.setattr(bench, "analyze", lambda b, **kw: {"ok": True, "faces": [], "plates": []})

    out = tmp_path / "out"
    bench.run(folder, out, quiet=True)
    header, rows = _read_csv(out)

    assert header == bench.CSV_COLUMNS
    for required in (
        "filename", "width", "height", "faces_found", "face_scores", "plates_found",
        "raw_ocr", "normalised_plate", "det_confidence", "ocr_confidence",
        "source_tier", "elapsed_ms", "row_kind", "plate_index",
    ):
        assert required in header
    assert len(rows) == 1


def test_zero_detection_image_still_gets_one_row(monkeypatch, stub_env, tmp_path):
    folder = _make_photos(tmp_path / "pics", ["empty.jpg"])
    monkeypatch.setattr(bench, "analyze", lambda b, **kw: {"ok": True, "faces": [], "plates": []})

    out = tmp_path / "out"
    summary = bench.run(folder, out, quiet=True)
    _, rows = _read_csv(out)

    assert len(rows) == 1
    row = rows[0]
    assert row["row_kind"] == "image"
    assert row["plate_index"] == ""
    assert row["faces_found"] == "0"
    assert row["plates_found"] == "0"
    assert row["raw_ocr"] == ""
    assert row["normalised_plate"] == ""
    assert row["status"] == "ok"
    assert row["width"] == "800" and row["height"] == "600"
    assert summary["images"] == 1
    assert summary["images_with_face"] == 0
    assert summary["images_with_plate"] == 0
    assert summary["failures"] == []


def test_multi_plate_image_emits_one_row_per_plate(monkeypatch, stub_env, tmp_path):
    folder = _make_photos(tmp_path / "pics", ["two_plates.jpg"])
    plates = [
        _box(0.1, 0.5, 0.2, 0.08, text="MH12AB1234", det_confidence=0.91,
             ocr_confidence=0.88, region="IN"),
        _box(0.6, 0.5, 0.2, 0.08, text="??garbage??", det_confidence=0.52,
             ocr_confidence=0.31, region=None),
    ]
    monkeypatch.setattr(
        bench, "analyze",
        lambda b, **kw: {"ok": True, "faces": [_box(score=0.97)], "plates": plates},
    )

    out = tmp_path / "out"
    summary = bench.run(folder, out, quiet=True)
    _, rows = _read_csv(out)

    assert len(rows) == 2
    assert [r["row_kind"] for r in rows] == ["plate", "plate"]
    assert [r["plate_index"] for r in rows] == ["1", "2"]
    # image-level values are repeated on every plate row
    assert {r["plates_found"] for r in rows} == {"2"}
    assert {r["faces_found"] for r in rows} == {"1"}
    assert {r["face_scores"] for r in rows} == {"0.970"}
    assert {r["filename"] for r in rows} == {"two_plates.jpg"}
    # per-plate values differ
    assert rows[0]["raw_ocr"] == "MH12AB1234"
    assert rows[0]["normalised_plate"] == "MH12AB1234"
    assert rows[0]["det_confidence"] == "0.910"
    assert rows[0]["ocr_confidence"] == "0.880"
    assert rows[0]["region"] == "IN"
    assert rows[1]["raw_ocr"] == "??garbage??"
    assert rows[1]["normalised_plate"] == ""   # did not validate
    assert rows[0]["source_tier"] == bench.DEFAULT_SOURCE_TIER
    # one IMAGE, two rows
    assert summary["images"] == 1
    assert summary["rows"] == 2
    assert summary["plate_rows"] == 2
    assert summary["plate_rows_normalised"] == 1


def test_explicit_source_overrides_the_default_tier(monkeypatch, stub_env, tmp_path):
    folder = _make_photos(tmp_path / "pics", ["p.jpg"])
    monkeypatch.setattr(
        bench, "analyze",
        lambda b, **kw: {"ok": True, "faces": [],
                         "plates": [_box(text="MH12AB1234", source="cloud-ocr")]},
    )
    out = tmp_path / "out"
    bench.run(folder, out, quiet=True)
    _, rows = _read_csv(out)
    assert rows[0]["source_tier"] == "cloud-ocr"


def test_unavailable_pipeline_is_distinct_from_found_nothing(monkeypatch, stub_env, tmp_path):
    folder = _make_photos(tmp_path / "pics", ["x.jpg"])
    # faces=None means "the model could not run", NOT "no faces present"
    monkeypatch.setattr(bench, "analyze", lambda b, **kw: {"ok": True, "faces": None, "plates": []})

    out = tmp_path / "out"
    summary = bench.run(folder, out, quiet=True)
    _, rows = _read_csv(out)

    assert rows[0]["faces_status"] == "unavailable"
    assert rows[0]["plates_status"] == "ok"
    assert summary["faces_unavailable"] == 1
    assert summary["plates_unavailable"] == 0


def test_skipped_pipelines_are_labelled(monkeypatch, stub_env, tmp_path):
    folder = _make_photos(tmp_path / "pics", ["x.jpg"])
    seen = {}

    def fake(b, do_faces=True, do_plates=True):
        seen["do_faces"] = do_faces
        seen["do_plates"] = do_plates
        return {"ok": True, "faces": None, "plates": []}

    monkeypatch.setattr(bench, "analyze", fake)
    out = tmp_path / "out"
    bench.run(folder, out, quiet=True, do_faces=False)
    _, rows = _read_csv(out)

    assert seen == {"do_faces": False, "do_plates": True}
    assert rows[0]["faces_status"] == "skipped"


# ---------------------------------------------------------------------------
# crops
# ---------------------------------------------------------------------------

def test_crop_file_naming(monkeypatch, stub_env, tmp_path):
    folder = _make_photos(tmp_path / "pics", ["car shot.jpg"])
    monkeypatch.setattr(
        bench, "analyze",
        lambda b, **kw: {
            "ok": True,
            "faces": [_box(0.1, 0.1, 0.1, 0.1, score=0.9), _box(0.3, 0.1, 0.1, 0.1, score=0.8)],
            "plates": [_box(0.1, 0.6, 0.2, 0.07, text="MH12AB1234"),
                       _box(0.5, 0.6, 0.2, 0.07, text="KA05XY9999")],
        },
    )

    out = tmp_path / "out"
    bench.run(folder, out, quiet=True)
    names = [p.name for p in stub_env["written"]]
    assert names == [
        "car shot__face1.jpg", "car shot__face2.jpg",
        "car shot__plate1.jpg", "car shot__plate2.jpg",
    ]
    # all under <out>/crops/
    assert all(p.parent == (out.resolve() / "crops") for p in stub_env["written"])

    _, rows = _read_csv(out)
    assert rows[0]["face_crops"] == "car shot__face1.jpg;car shot__face2.jpg"
    assert rows[0]["plate_crop"] == "car shot__plate1.jpg"
    assert rows[1]["plate_crop"] == "car shot__plate2.jpg"
    assert rows[0]["crop_stem"] == "car shot"


def test_duplicate_stems_do_not_overwrite_each_other(monkeypatch, stub_env, tmp_path):
    root = tmp_path / "pics"
    _make_photos(root / "a", ["same.jpg"])
    _make_photos(root / "b", ["same.jpg"])
    monkeypatch.setattr(
        bench, "analyze",
        lambda b, **kw: {"ok": True, "faces": [_box(score=0.9)], "plates": []},
    )

    out = tmp_path / "out"
    bench.run(root, out, recursive=True, quiet=True)
    names = sorted(p.name for p in stub_env["written"])
    assert names == ["same-2__face1.jpg", "same__face1.jpg"]


def test_no_crops_flag_writes_nothing(monkeypatch, stub_env, tmp_path):
    folder = _make_photos(tmp_path / "pics", ["x.jpg"])
    monkeypatch.setattr(
        bench, "analyze",
        lambda b, **kw: {"ok": True, "faces": [_box(score=0.9)], "plates": []},
    )
    out = tmp_path / "out"
    bench.run(folder, out, quiet=True, write_crops=False)
    assert stub_env["written"] == []


def test_undecodable_image_is_marked_not_crashed(monkeypatch, stub_env, tmp_path):
    folder = _make_photos(tmp_path / "pics", ["broken.jpg"])
    monkeypatch.setattr(bench, "decode_image", lambda b: (None, 0, 0))
    monkeypatch.setattr(bench, "analyze", lambda b, **kw: {"ok": False, "faces": None, "plates": None})

    out = tmp_path / "out"
    summary = bench.run(folder, out, quiet=True)
    _, rows = _read_csv(out)

    assert rows[0]["status"] == "decode_failed"
    assert rows[0]["width"] == "0"
    assert len(summary["failures"]) == 1
    assert stub_env["written"] == []
    # a corrupt file is NOT a missing model — do not mislabel it "unavailable"
    assert rows[0]["faces_status"] == "no_image"
    assert rows[0]["plates_status"] == "no_image"
    assert summary["faces_unavailable"] == 0
    # and its ~0 ms must not pollute the timing stats
    assert summary["cold_ms"] is None
    assert summary["cold_failed"] is True
    assert summary["warm_count"] == 0


# ---------------------------------------------------------------------------
# resilience
# ---------------------------------------------------------------------------

def test_one_exploding_image_does_not_abort_the_run(monkeypatch, stub_env, tmp_path):
    folder = _make_photos(tmp_path / "pics", ["a.jpg", "b.jpg", "c.jpg"])

    def flaky(img_bytes, **kw):
        flaky.calls += 1
        if flaky.calls == 2:
            raise RuntimeError("onnxruntime exploded")
        return {"ok": True, "faces": [_box(score=0.5)], "plates": []}

    flaky.calls = 0
    monkeypatch.setattr(bench, "analyze", flaky)

    out = tmp_path / "out"
    summary = bench.run(folder, out, quiet=True)
    _, rows = _read_csv(out)

    assert len(rows) == 3                       # the run completed
    assert [r["filename"] for r in rows] == ["a.jpg", "b.jpg", "c.jpg"]
    bad = rows[1]
    assert bad["status"] == "error"
    assert "RuntimeError" in bad["error"]
    assert "onnxruntime exploded" in bad["error"]
    assert rows[0]["status"] == "ok" and rows[2]["status"] == "ok"
    assert summary["images"] == 3
    assert len(summary["failures"]) == 1
    assert summary["failures"][0][0] == "b.jpg"


def test_unreadable_file_is_recorded_as_an_error(monkeypatch, stub_env, tmp_path):
    folder = tmp_path / "pics"
    folder.mkdir()
    (folder / "ghost.jpg").write_bytes(b"x")
    monkeypatch.setattr(bench, "analyze", lambda b, **kw: {"ok": True, "faces": [], "plates": []})

    real_read = Path.read_bytes

    def boom(self, *a, **kw):
        if self.name == "ghost.jpg":
            raise OSError("Input/output error")
        return real_read(self, *a, **kw)

    monkeypatch.setattr(Path, "read_bytes", boom)
    out = tmp_path / "out"
    bench.run(folder, out, quiet=True)
    _, rows = _read_csv(out)
    assert rows[0]["status"] == "error"
    assert "OSError" in rows[0]["error"]


# ---------------------------------------------------------------------------
# ordering, timing, summary
# ---------------------------------------------------------------------------

def test_rows_are_in_sorted_order_even_with_threads(monkeypatch, stub_env, tmp_path):
    names = ["{0:02d}.jpg".format(i) for i in range(12)]
    folder = _make_photos(tmp_path / "pics", names)
    monkeypatch.setattr(bench, "analyze", lambda b, **kw: {"ok": True, "faces": [], "plates": []})

    out_a = tmp_path / "a"
    out_b = tmp_path / "b"
    bench.run(folder, out_a, quiet=True, threads=1)
    bench.run(folder, out_b, quiet=True, threads=4)

    _, rows_a = _read_csv(out_a)
    _, rows_b = _read_csv(out_b)
    assert [r["filename"] for r in rows_a] == sorted(names)
    assert [r["filename"] for r in rows_b] == sorted(names)
    assert [r["image_index"] for r in rows_a] == [str(i) for i in range(12)]


def test_cold_and_warm_are_reported_separately(monkeypatch, stub_env, tmp_path):
    folder = _make_photos(tmp_path / "pics", ["a.jpg", "b.jpg", "c.jpg"])
    monkeypatch.setattr(bench, "analyze", lambda b, **kw: {"ok": True, "faces": [], "plates": []})

    out = tmp_path / "out"
    summary = bench.run(folder, out, quiet=True)
    _, rows = _read_csv(out)

    assert [r["is_cold"] for r in rows] == ["1", "0", "0"]
    assert summary["cold_ms"] is not None
    assert summary["warm_count"] == 2
    assert summary["warm_mean_ms"] is not None
    assert summary["warm_median_ms"] is not None


def test_failed_images_are_excluded_from_timing_stats(monkeypatch, stub_env, tmp_path):
    folder = _make_photos(tmp_path / "pics", ["a.jpg", "b.jpg", "c.jpg"])

    def flaky(img_bytes, **kw):
        flaky.calls += 1
        if flaky.calls == 2:
            raise RuntimeError("boom")
        return {"ok": True, "faces": [], "plates": []}

    flaky.calls = 0
    monkeypatch.setattr(bench, "analyze", flaky)

    summary = bench.run(folder, tmp_path / "out", quiet=True)
    assert summary["cold_ms"] is not None       # image 1 succeeded
    assert summary["cold_failed"] is False
    assert summary["warm_count"] == 1           # only c.jpg; b.jpg failed
    assert len(summary["failures"]) == 1


def test_limit_and_recursive(monkeypatch, stub_env, tmp_path):
    root = tmp_path / "pics"
    _make_photos(root, ["a.jpg", "b.jpg"])
    _make_photos(root / "deep", ["c.jpg"])
    monkeypatch.setattr(bench, "analyze", lambda b, **kw: {"ok": True, "faces": [], "plates": []})

    out = tmp_path / "out"
    bench.run(root, out, recursive=True, limit=2, quiet=True)
    _, rows = _read_csv(out)
    assert [r["filename"] for r in rows] == ["a.jpg", "b.jpg"]
    assert rows[0]["relpath"] == "a.jpg"

    out2 = tmp_path / "out2"
    bench.run(root, out2, recursive=True, quiet=True)
    _, rows2 = _read_csv(out2)
    assert any(r["relpath"].replace("\\", "/") == "deep/c.jpg" for r in rows2)


def test_empty_folder_exits_cleanly(tmp_path):
    folder = tmp_path / "pics"
    folder.mkdir()
    with pytest.raises(SystemExit):
        bench.run(folder, tmp_path / "out", quiet=True)


def test_missing_folder_exits_cleanly(tmp_path):
    with pytest.raises(SystemExit):
        bench.run(tmp_path / "nope", tmp_path / "out", quiet=True)


def test_summary_prints_without_crashing(monkeypatch, stub_env, tmp_path, capsys):
    folder = _make_photos(tmp_path / "pics", ["a.jpg", "b.jpg"])
    monkeypatch.setattr(
        bench, "analyze",
        lambda b, **kw: {"ok": True, "faces": [_box(score=0.9)],
                         "plates": [_box(text="MH12AB1234", det_confidence=0.9)]},
    )
    bench.run(folder, tmp_path / "out", quiet=False)
    out = capsys.readouterr().out
    assert "BENCH SUMMARY" in out
    assert "images with >=1 plate" in out
    assert "cold (image 1" in out


# ---------------------------------------------------------------------------
# the defensive app.anpr import
# ---------------------------------------------------------------------------

def test_normaliser_prefers_a_richer_helper_when_present(monkeypatch):
    """If anpr grows a stronger helper, the bench must pick it up automatically."""
    from app import anpr

    monkeypatch.setattr(anpr, "normalize_plate_strict", lambda t: "FROM-RICHER", raising=False)
    assert bench.normalise_plate_text("mh12ab1234") == "FROM-RICHER"
    assert bench._resolve_normaliser()[1] == "normalize_plate_strict"


def test_normaliser_falls_back_when_the_richer_helper_raises(monkeypatch):
    from app import anpr

    def exploding(_t):
        raise ValueError("nope")

    monkeypatch.setattr(anpr, "normalize_plate_strict", exploding, raising=False)
    # falls through to the known-good baseline normalize_plate()
    assert bench.normalise_plate_text("MH 12 AB 1234") == "MH12AB1234"


def test_normaliser_falls_back_when_the_richer_helper_declines(monkeypatch):
    from app import anpr

    monkeypatch.setattr(anpr, "normalize_plate_strict", lambda _t: None, raising=False)
    assert bench.normalise_plate_text("MH12AB1234") == "MH12AB1234"


def test_normaliser_accepts_a_tuple_returning_helper(monkeypatch):
    """A (plate, confidence) return value is coerced to the plate string."""
    from app import anpr

    monkeypatch.setattr(anpr, "best_plate", lambda t: ("MH12AB1234", 0.91), raising=False)
    assert bench.normalise_plate_text("anything") == "MH12AB1234"
    assert bench._resolve_normaliser()[1] == "best_plate"


def test_normaliser_ignores_a_non_callable_attribute(monkeypatch):
    from app import anpr

    monkeypatch.setattr(anpr, "normalize_plate_strict", "not-a-function", raising=False)
    assert bench.normalise_plate_text("MH 12 AB 1234") == "MH12AB1234"
    assert bench._resolve_normaliser()[1] == "normalize_plate"


def test_real_anpr_normaliser_round_trip():
    """Against the REAL app.anpr (pure stdlib, safe to import here)."""
    assert bench.normalise_plate_text("MH 12 AB 1234") == "MH12AB1234"
    assert bench.normalise_plate_text("mh12ab1234") == "MH12AB1234"
    assert bench.normalise_plate_text("totally-not-a-plate") is None
    assert bench.normalise_plate_text("") is None
    assert bench.normalise_plate_text(None) is None
    assert bench._resolve_normaliser()[1] == "normalize_plate"


# ---------------------------------------------------------------------------
# the dict-returning ("detail") normaliser and its extra CSV columns
# ---------------------------------------------------------------------------

def test_detail_normaliser_fills_the_audit_columns(monkeypatch):
    from app import anpr

    monkeypatch.setattr(
        anpr, "normalize_plate_detail",
        lambda t: {"raw": t, "candidate": "MH02FX2660", "normalised": "MH02FX2660",
                   "format": "standard", "state": "MH", "fixes": ["pos2 O->0", "pos3 I->1"]},
        raising=False,
    )
    info = bench.normalise_plate_info("MHO2FX266O")
    assert info["normalised"] == "MH02FX2660"
    assert info["format"] == "standard"
    assert info["state"] == "MH"
    assert info["fixes"] == "pos2 O->0;pos3 I->1"


def test_detail_normaliser_handles_a_bh_series_shape(monkeypatch):
    from app import anpr

    monkeypatch.setattr(
        anpr, "normalize_plate_detail",
        lambda t: {"normalised": "22BH1234AB", "format": "bh", "state": None, "fixes": []},
        raising=False,
    )
    info = bench.normalise_plate_info("22BH1234AB")
    assert info["normalised"] == "22BH1234AB"
    assert info["format"] == "bh"
    assert info["state"] == ""      # None -> blank, never the string "None"
    assert info["fixes"] == ""


@pytest.mark.parametrize("bad", [None, {}, {"normalised": ""}, "a-bare-string", 42,
                                 {"normalised": None}])
def test_detail_normaliser_declining_falls_back_to_the_string_path(monkeypatch, bad):
    """A useless return value must hand over to the plain string normaliser.

    NOTE: in the current app.anpr, normalize_plate() is a THIN WRAPPER over
    normalize_plate_detail(), so we cannot break the detail helper and still
    expect the real baseline to work. We assert the WIRING instead, with a
    sentinel standing in for the string path.
    """
    from app import anpr

    monkeypatch.setattr(anpr, "normalize_plate_detail", lambda t: bad, raising=False)
    monkeypatch.setattr(bench, "normalise_plate_text", lambda t: "FELL-BACK")

    info = bench.normalise_plate_info("MH 12 AB 1234")
    assert info["normalised"] == "FELL-BACK"
    assert info["format"] == "" and info["state"] == "" and info["fixes"] == ""


def test_detail_normaliser_raising_falls_back(monkeypatch):
    from app import anpr

    def exploding(_t):
        raise RuntimeError("anpr mid-edit")

    monkeypatch.setattr(anpr, "normalize_plate_detail", exploding, raising=False)
    monkeypatch.setattr(bench, "normalise_plate_text", lambda t: "FELL-BACK")
    assert bench.normalise_plate_info("MH12AB1234")["normalised"] == "FELL-BACK"


def test_no_detail_helper_at_all_uses_the_string_path(monkeypatch):
    """Older/other anpr with no dict-returning helper: CSV shape must not change."""
    monkeypatch.setattr(bench, "_PREFERRED_DETAIL_NORMALISERS", ("does_not_exist_anywhere",))
    bench._detail_normaliser = False
    bench._detail_normaliser_name = None

    info = bench.normalise_plate_info("MH 12 AB 1234")
    assert info["normalised"] == "MH12AB1234"     # real normalize_plate(), untouched
    assert set(info) == {"normalised", "format", "state", "fixes"}
    assert info["format"] == "" and info["state"] == "" and info["fixes"] == ""
    assert bench._resolve_detail_normaliser()[0] is None


def test_detail_normaliser_alternate_key_names(monkeypatch):
    """anpr is in flux — accept 'normalized'/'plate' as well as 'normalised'."""
    from app import anpr

    for key in ("normalized", "plate", "value"):
        monkeypatch.setattr(anpr, "normalize_plate_detail",
                            lambda t, k=key: {k: "KA05XY9999"}, raising=False)
        bench._detail_normaliser = False
        bench._detail_normaliser_name = None
        assert bench.normalise_plate_info("x")["normalised"] == "KA05XY9999"


def test_empty_text_needs_no_normaliser_at_all():
    info = bench.normalise_plate_info("")
    assert info == {"normalised": "", "format": "", "state": "", "fixes": ""}


def test_audit_columns_reach_the_csv(monkeypatch, stub_env, tmp_path):
    from app import anpr

    folder = _make_photos(tmp_path / "pics", ["p.jpg"])
    monkeypatch.setattr(
        anpr, "normalize_plate_detail",
        lambda t: {"normalised": "MH02FX2660", "format": "standard",
                   "state": "MH", "fixes": ["pos2 O->0"]},
        raising=False,
    )
    monkeypatch.setattr(
        bench, "analyze",
        lambda b, **kw: {"ok": True, "faces": [],
                         "plates": [_box(text="MHO2FX266O", det_confidence=0.9)]},
    )

    out = tmp_path / "out"
    summary = bench.run(folder, out, quiet=True)
    header, rows = _read_csv(out)

    assert "plate_format" in header and "plate_state" in header and "normalise_fixes" in header
    assert rows[0]["normalised_plate"] == "MH02FX2660"
    assert rows[0]["plate_format"] == "standard"
    assert rows[0]["plate_state"] == "MH"
    assert rows[0]["normalise_fixes"] == "pos2 O->0"
    # a read that only validated after repairs is flagged in the summary
    assert summary["plate_rows_coerced"] == 1
    assert summary["normaliser"] == "normalize_plate_detail"


def test_real_anpr_detail_normaliser_round_trip():
    """Against the REAL app.anpr, whichever helper it currently exposes."""
    info = bench.normalise_plate_info("MH 12 AB 1234")
    assert info["normalised"] == "MH12AB1234"
    assert bench.normalise_plate_info("totally-not-a-plate")["normalised"] == ""
    # extras are either populated or blank, but the keys always exist
    assert set(info) == {"normalised", "format", "state", "fixes"}


# ---------------------------------------------------------------------------
# argparse wiring
# ---------------------------------------------------------------------------

def test_cli_parses_every_documented_flag():
    args = bench.build_parser().parse_args(
        ["/data", "--out", "/out", "--recursive", "--limit", "50",
         "--no-faces", "--threads", "3", "--no-crops"]
    )
    assert args.folder == "/data"
    assert args.out == "/out"
    assert args.recursive is True
    assert args.limit == 50
    assert args.no_faces is True and args.no_plates is False
    assert args.threads == 3
    assert args.no_crops is True


def test_cli_refuses_to_disable_both_pipelines():
    with pytest.raises(SystemExit):
        bench.main(["/data", "--no-faces", "--no-plates"])


def test_script_imports_no_forbidden_app_module():
    """The bench must never pull in config/database/models/storage (AST-checked)."""
    import ast

    tree = ast.parse((_SCRIPTS_DIR / "plate_face_bench.py").read_text())
    forbidden = {"config", "database", "models", "storage"}
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod == "app":
                imported.update("app.{0}".format(a.name) for a in node.names)
            else:
                imported.add(mod)
    bad = [m for m in imported if m.split(".")[1:2] and m.split(".")[0] == "app"
           and m.split(".")[1] in forbidden]
    assert not bad, "forbidden imports: {0}".format(bad)
    # and the only app modules it may touch:
    app_mods = sorted(m for m in imported if m.split(".")[0] == "app")
    assert app_mods == ["app.anpr", "app.vision_local"], app_mods
