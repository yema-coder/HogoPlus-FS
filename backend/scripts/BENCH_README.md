# Camera-AI accuracy bench (`plate_face_bench.py`)

Offline measuring tape for the on-server camera AI. Point it at a folder of photos;
it runs **the exact pipeline the API uses** (`app.vision_local.analyze_image`) on every
image and writes a CSV plus crop JPEGs you can eyeball.

**What it touches:** the photo folder (read) and the output folder (write). Nothing else.
No database, no Redis, no S3/R2, no API call, no running container. It imports only
`app.vision_local` and `app.anpr` — never `app.config`, `app.database`, `app.models` or
`app.storage` — so there is no connection string anywhere in its import graph.
CPU-only (`vision_local` pins `CPUExecutionProvider`).

---

## (a) On the EC2 box, using the image that is already built

The models (YOLOv9 plate detector + CCT-XS OCR) are baked into `hogoplus-backend:latest`
at build time, so there is **nothing to build and nothing to download**.

One catch: the image was built *before* this script existed (the Dockerfile does
`COPY backend/ /app/backend/` at build time), so **the script has to be mounted in**.
Do not rebuild the image just for this — mount the one file:

```bash
mkdir -p /home/ubuntu/photos /home/ubuntu/bench-out
# ...copy your photos into /home/ubuntu/photos first...

sudo docker run --rm \
  --network none \
  --cpus 1.5 --memory 2g \
  -v /home/ubuntu/photos:/data:ro \
  -v /home/ubuntu/bench-out:/out \
  -v /home/ubuntu/HogoPlus-FS/backend/scripts/plate_face_bench.py:/app/backend/scripts/plate_face_bench.py:ro \
  hogoplus-backend:latest \
  python scripts/plate_face_bench.py /data --out /out --limit 10
```

(Adjust the repo path if your checkout is not at `/home/ubuntu/HogoPlus-FS`.)

Then widen it once the small batch looks right — drop `--limit 10`, add `--recursive`
if your photos are in sub-folders.

**Read this before you run it on hundreds of photos:**

* This runs on the **production HOST's CPU and RAM** — the same 4 GB box that is serving
  the live API. A new throwaway container is started; the running `hogoplus-backend`
  container is **not** touched, restarted or entered. But the CPU is shared.
  **Start with `--limit 10`**, watch `htop`, then scale up.
* `--cpus 1.5 --memory 2g` is the guard rail that stops the bench starving uvicorn.
  Keep it. If the box feels sluggish, drop to `--cpus 1`.
* `--network none` is deliberate: it *proves* the run cannot reach the database or any
  network service. It works because the ONNX models are already in the image. If the run
  reports `plates_status=unavailable`, the image's model cache is broken — rebuild it, do
  not just remove `--network none`.
* Keep `--threads 1` (the default) on this box. `vision_local` serialises inference behind
  a global lock anyway, so more threads buy almost nothing and only add memory pressure.
* The container writes as root, so hand the output back to yourself afterwards:
  `sudo chown -R ubuntu:ubuntu /home/ubuntu/bench-out`
* `app/vision_local.py` and `app/anpr.py` come from **the image**, not from your git
  checkout. That is usually what you want — you are measuring what production actually
  runs. If the image is behind HEAD, the numbers reflect the image. The summary line
  `plate normaliser used : app.anpr.<name>` tells you which normaliser the image has.

Copy the results down to your laptop to look at the crops:

```bash
scp -r ubuntu@<host>:/home/ubuntu/bench-out ./bench-out
```

---

## (b) Locally on a Mac, in a venv

Needs **Python 3.10+** (the server runs 3.11; macOS's stock `/usr/bin/python3` is 3.9 and
will not do). `brew install python@3.11` if you do not have one.

```bash
cd /path/to/HogoPlus-FS/backend
python3.11 -m venv .venv-bench
source .venv-bench/bin/activate
pip install opencv-python-headless==5.0.0.93 open-image-models==0.6.0 \
            fast-plate-ocr==1.1.0 onnxruntime==1.27.0 numpy

python scripts/plate_face_bench.py ~/Desktop/plate-photos --out ~/Desktop/bench-out
```

The plate detector and OCR models **download from the internet on first run** (a few tens
of MB, cached under `~/.cache/open-image-models` and `~/.cache/fast-plate-ocr`), so the
very first run needs connectivity and is slow. The YuNet face model is not downloaded —
it is vendored in the repo at `backend/ml_models/yunet.onnx`.

Only these five packages are needed. Do **not** `pip install -r requirements.txt` for this
— that pulls the whole server (SQLAlchemy, Celery, etc.) which the bench never imports.

---

## Where things go

| | |
|---|---|
| **photos in** | any folder you pass as the first argument. `.jpg .jpeg .png .webp`, case-insensitive. Dot-files skipped. Add `--recursive` for sub-folders. |
| **CSV out** | `<out>/results.csv` |
| **crops out** | `<out>/crops/<stem>__face1.jpg`, `<out>/crops/<stem>__plate1.jpg`, … |

Crops are cut from the **original full-resolution** image (not the 1280 px copy the model
sees) with an 8 % margin, so a plate crop is readable. If two folders contain the same
filename, the second one's crops get a `-2` suffix — the `crop_stem` column tells you which
stem an image got.

Processing order is `sorted()`, so two runs over the same folder produce byte-comparable
CSVs. One bad image never aborts the run: it gets a row with `status=error`.

### Flags

| flag | meaning |
|---|---|
| `--out DIR` | output directory (default `./bench-out`) |
| `--recursive` | walk sub-folders |
| `--limit N` | only the first N images, sorted. **Use this for your first run.** |
| `--no-faces` / `--no-plates` | skip one pipeline (faster if you only care about the other) |
| `--threads N` | worker threads, default 1. See the note above — rarely worth raising. |
| `--no-crops` | CSV only, no JPEGs |
| `--crop-margin F` | margin around each crop as a fraction of the box (default `0.08`) |
| `--traceback` | print a full traceback for each failed image |
| `--quiet` | no progress or summary |

Exit code is `1` if any image failed, else `0`.

---

## CSV columns

One row per **plate**. An image with 3 plates gives 3 rows; an image with no plate still
gives exactly 1 row. **`row_kind` is how you tell them apart** — never guess from the
filename.

| column | meaning |
|---|---|
| `image_index` | 0-based position in the sorted file list. Same image = same index across rows. |
| `filename` | basename |
| `relpath` | path relative to the folder you scanned (useful with `--recursive`) |
| `width`, `height` | **original** pixel size. `0` means the file could not be decoded. |
| `row_kind` | `plate` = this row describes one detected plate. `image` = no plate on this row (none found, pipeline skipped, or the image failed). |
| `plate_index` | `1..N` on `plate` rows, blank on `image` rows |
| `faces_found` | face count for the **image** (repeated on every row of that image) |
| `face_scores` | YuNet scores, 3dp, semicolon-joined, highest first |
| `plates_found` | plate count for the **image** (repeated on every row of that image) |
| `raw_ocr` | verbatim OCR output for **this** plate |
| `normalised_plate` | `raw_ocr` pushed through the Indian-plate normaliser, or **blank if it did not validate** |
| `det_confidence` | YOLOv9 confidence that this box *is* a plate, 3dp |
| `ocr_confidence` | mean per-character OCR confidence, 3dp |
| `source_tier` | which engine produced this plate — `local:yolov9-t+cct-xs` for the on-box pipeline |
| `region` | plate-layout/region hint from the OCR model. Often `Unknown`; informational only. |
| `plate_format` | layout the normaliser matched: `standard` (`MH12AB1234`) or `bh` (BH-series, `22BH1234AB`). Blank if it did not validate. |
| `plate_state` | the state code the normaliser validated. Blank for BH-series (they have no state) and for non-validating reads. |
| `normalise_fixes` | **read this one.** Positional confusable repairs the normaliser had to apply to make the read legal, e.g. `pos2 O->0;pos9 O->0`. Blank means the OCR text was already a clean plate. |
| `faces_status` | `ok` / `unavailable` (model missing!) / `no_image` (file unreadable) / `skipped` (`--no-faces`) |
| `plates_status` | same values, for the plate pipeline |
| `elapsed_ms` | `analyze_image()` only — the honest pipeline cost |
| `total_ms` | the above plus this tool's own decode and crop writing |
| `is_cold` | `1` on the first image processed. **Its time includes model load — ignore it when judging speed.** |
| `status` | `ok` / `decode_failed` / `error` |
| `error` | exception type and message when `status=error`, else blank |
| `crop_stem` | the stem used for this image's crop filenames |
| `face_crops` | semicolon-joined face crop filenames written for this image |
| `plate_crop` | crop filename for **this** plate row |

---

## Reading the numbers

**The three columns that matter for accuracy:**

* **`normalised_plate` is your scoreboard.** Blank means the OCR text could not be coerced
  into a legal Indian plate (`XX00XX0000` with a valid state code, or a BH-series plate).
  Sort the CSV by `normalised_plate` and compare against what you know the plate actually
  was — that is your real read rate. `raw_ocr` non-empty + `normalised_plate` blank is the
  interesting bucket: the plate was *found* but *misread*.
* **`normalise_fixes` tells you how much work the normaliser did.** A non-blank value means
  the OCR text was *not* a legal plate and only became one after positional confusable
  repairs (`O`->`0`, `I`->`1`, ...). Those rows are softer than their `ocr_confidence`
  suggests: the normaliser made a plausible guess. The summary counts them. A row with a
  `normalised_plate` **and** a blank `normalise_fixes` is the gold standard.
* **`det_confidence`** — did it find the plate? The detector is thresholded at `0.4`, so
  every row you see is already above that. `>0.8` is a confident box. Low `det_confidence`
  with a sensible plate usually means a small or angled plate.
* **`ocr_confidence`** — did it read the plate *right*? This is the mean over characters, so
  one bad character drags it down. In practice `>0.85` with a non-blank `normalised_plate`
  is trustworthy; `<0.6` is a coin flip even when the text looks plausible. Treat the two
  confidences separately — a `0.95` box with `0.45` OCR means "definitely a plate, don't
  trust these characters".

**Faces:** `face_scores` are YuNet detection scores, thresholded at `0.6`. These are
*detection* scores — "something here is a face". The pipeline never identifies anyone.
A high score on a non-face crop is a false positive worth looking at in `crops/`.

**Speed:** read the two summary lines, not the average of the column.
`cold` is image 1 and includes loading three ONNX models — on a cold EC2 container expect
seconds, not milliseconds. `warm` mean/median is the number to quote for throughput.
Failed images are excluded from both so a corrupt file cannot flatter the median.

**If `plates_status` or `faces_status` says `unavailable`**, stop reading the accuracy
numbers — a model did not load and those zeros are not misses, they are nothing. On the
EC2 image that means the baked cache is broken; locally it means a pip install is missing.
`no_image` is different and benign: that one file is corrupt.

**Which normaliser ran.** The summary prints `plate normaliser used : app.anpr.<name>`.
The bench prefers `normalize_plate_detail()` — that is what fills `plate_format`,
`plate_state` and `normalise_fixes` — and falls back to plain `normalize_plate()` if the
image's `anpr.py` predates it. In that case those three columns are simply blank and
`normalised_plate` still works. If the name is not what you expect, the image is running a
different `anpr.py` than your checkout.

---

## Tests

The tool has stub tests that need **no** heavy dependencies and **no** database — the
vision call and the JPEG writer are monkeypatched:

```bash
# from the repo root
python -m pytest backend/scripts/test_bench_tool.py
```

They deliberately live in `backend/scripts/`, not `backend/tests/`: `backend/pytest.ini`
sets `testpaths = tests`, and `backend/tests/conftest.py` has session-scoped autouse
fixtures that force a `DATABASE_URL` and call `drop_all()` against a live Postgres. These
tests must be runnable on a laptop with nothing running, so they sit next to the script and
are invoked by explicit path. Running them does not start Postgres or Redis.
