"""BUG 5 backfill — fix incident photos stored SIDEWAYS by the broken AR build.

The pre-fix Android AR capture wrote the sensor-native LANDSCAPE JPEG with no
rotation and no EXIF. Those photos display rotated on the dashboard and silently
broke server face/plate detection (OpenCV `imdecode` ignores EXIF). This one-time
script rotates such photos 90° clockwise so they are UPRIGHT, overwrites the same
storage key (so links keep working), then re-runs local face/plate analysis +
ANPR so the regenerated detection reflects the corrected orientation.

Run from /app/backend:
    python scripts/backfill_rotate_ar_photos.py --since 2026-06-01 --dry-run
    python scripts/backfill_rotate_ar_photos.py --since 2026-06-01
    python scripts/backfill_rotate_ar_photos.py --incident-id <uuid>
    python scripts/backfill_rotate_ar_photos.py --since 2026-06-01 --degrees 270 --force-all

Safety:
  * By default ONLY rotates photos whose stored pixels are LANDSCAPE (w >= h) —
    the signature of the broken AR capture. Genuinely-portrait photos are skipped
    (override with --force-all).
  * source='gallery' test uploads are skipped (they were transcoded upright
    already); pass --include-gallery to rotate them too.
  * Video incidents are skipped.
  * --dry-run lists what WOULD change without touching storage or the DB.
  * Re-analysis loads the ONNX models (~450-660MB RSS) — run where they exist.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("backfill_rotate")

_CV_ROTATION = {}


def _rotate(data: bytes, degrees: int):
    """(rotated_jpeg_bytes, (orig_w, orig_h), (new_w, new_h)) or (None, dims|None, None)."""
    import cv2
    import numpy as np

    if not _CV_ROTATION:
        _CV_ROTATION.update(
            {
                90: cv2.ROTATE_90_CLOCKWISE,
                180: cv2.ROTATE_180,
                270: cv2.ROTATE_90_COUNTERCLOCKWISE,
            }
        )
    arr = np.frombuffer(data, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        return None, None, None
    h, w = img.shape[:2]
    rotated = cv2.rotate(img, _CV_ROTATION[degrees])
    ok, buf = cv2.imencode(".jpg", rotated, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
    if not ok:
        return None, (w, h), None
    return buf.tobytes(), (w, h), (rotated.shape[1], rotated.shape[0])


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", help="YYYY-MM-DD; only incidents created on/after this date")
    ap.add_argument("--incident-id", help="rotate a single incident by id (ignores --since/filters)")
    ap.add_argument("--degrees", type=int, default=90, choices=[90, 180, 270],
                    help="clockwise rotation to apply (default 90)")
    ap.add_argument("--force-all", action="store_true",
                    help="rotate even if the stored image is already portrait")
    ap.add_argument("--include-gallery", action="store_true",
                    help="also rotate source='gallery' test uploads")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    from sqlalchemy import delete, select

    from app import tasks
    from app.database import SessionLocal
    from app.models import Incident, PhotoAnalysis
    from app.storage import S3Storage, get_storage

    storage = get_storage()

    def _overwrite(key: str, content: bytes) -> None:
        if isinstance(storage, S3Storage):
            storage.client.put_object(
                Bucket=storage.bucket, Key=key, Body=content, ContentType="image/jpeg"
            )
        else:
            storage.path_for(key).write_bytes(content)

    # ---- select candidate incidents ----
    async with SessionLocal() as session:
        if args.incident_id:
            q = select(Incident).where(Incident.id == args.incident_id)
        else:
            q = select(Incident).where(
                Incident.photo_key.isnot(None), Incident.video_key.is_(None)
            )
            if args.since:
                since = datetime.strptime(args.since, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                q = q.where(Incident.created_at >= since)
            if not args.include_gallery:
                q = q.where((Incident.source.is_(None)) | (Incident.source != "gallery"))
        rows = (await session.execute(q)).scalars().all()
        keyinfo = {str(i.id): i.photo_key for i in rows if i.photo_key}

    log.info("Found %d candidate incident(s).", len(keyinfo))
    rotated_ids: list[str] = []
    skipped_portrait = 0
    for iid, key in keyinfo.items():
        try:
            data = storage.get(key)
        except Exception as e:
            log.warning("  %s: cannot read %s (%s) — skip", iid[:8], key, e)
            continue
        new_bytes, orig_dims, new_dims = _rotate(data, args.degrees)
        if orig_dims is None:
            log.warning("  %s: decode failed — skip", iid[:8])
            continue
        w, h = orig_dims
        if w < h and not args.force_all:
            skipped_portrait += 1
            continue
        if new_bytes is None:
            log.warning("  %s: re-encode failed — skip", iid[:8])
            continue
        log.info(
            "  %s: %dx%d -> %dx%d (rotate %d CW)%s",
            iid[:8], w, h, new_dims[0], new_dims[1], args.degrees,
            " [DRY-RUN]" if args.dry_run else "",
        )
        if args.dry_run:
            continue
        _overwrite(key, new_bytes)
        rotated_ids.append(iid)

    if skipped_portrait:
        log.info("Skipped %d already-portrait photo(s) (use --force-all to include).", skipped_portrait)
    if args.dry_run:
        log.info("DRY-RUN complete — nothing changed.")
        return

    # ---- clear stale analysis + re-run face/plate detection on the corrected image ----
    for iid in rotated_ids:
        async with SessionLocal() as session:
            inc = await session.get(Incident, iid)
            if inc is None:
                continue
            await session.execute(delete(PhotoAnalysis).where(PhotoAnalysis.incident_id == inc.id))
            inc.detected_plate = None
            inc.plate_confidence = None
            inc.plate_source = None
            inc.plate_status = "pending"
            inc.plate_reason = None
            await session.commit()
        # force=True runs faces+plates regardless of the global switches (same as a
        # gallery test). Classification LLM is intentionally NOT re-run.
        res = await tasks._analyze_photos_async("incident", iid, force=True)
        if res.get("plate_enabled", True) and not res.get("found_plate"):
            await tasks._detect_plate_async("incident", iid)
        log.info("  re-analyzed %s", iid[:8])

    log.info("Done. Rotated + re-analyzed %d incident(s).", len(rotated_ids))


if __name__ == "__main__":
    asyncio.run(main())
