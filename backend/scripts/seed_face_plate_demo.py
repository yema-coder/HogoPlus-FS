"""Seed ONE ephemeral demo incident carrying a realistic face + number-plate photo
and the matching photo-analysis rows, so the rebuilt mobile incident-detail screen
(face strips + editable plate preserving `original_text`) can be verified end-to-end
by Demo CGM D500 (+919000000500 / OTP 123456).

DEV/SANDBOX ONLY — this is a manual script. It is NOT wired into any migration,
startup seed, or the deploy pipeline, so it never runs against production.

Why this exists: incident visibility is scoped by `incident.is_demo == employee.is_demo`,
so a demo account only sees demo rows. The real/production incidents that happen to carry
faces + plates are is_demo=false (→ not visible to the demo account). This fixture puts a
2-faces + 2-plates incident INSIDE the demo bubble.

Flagged is_demo=true, is_demo_seed=FALSE → it is an EPHEMERAL demo row that the hourly
`demo_cleanup` sweep AUTO-PURGES (with its media + analysis). Re-run this script to recreate
it whenever you need to re-verify.

Idempotent: keyed on client_uuid='demo-faceplate-fixture'.

Run:  cd /app/backend && python scripts/seed_face_plate_demo.py
"""
from __future__ import annotations

import asyncio
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image, ImageDraw, ImageFont  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models import (  # noqa: E402
    Employee,
    Incident,
    PhotoAnalysis,
    PhotoFace,
    PhotoPlate,
    Role,
)
from app.storage import get_storage  # noqa: E402

FIXTURE_UUID = "demo-faceplate-fixture"
PLATE_TEXT = "MH12AB1234"
PLATE_TEXT_2 = "MH14GH7777"
W, H = 1200, 1600  # portrait (post-AR captures are portrait)

# Normalised (0..1) boxes that MATCH the drawn regions below.
FACE_BOXES = [
    {"x": 0.17, "y": 0.09, "w": 0.24, "h": 0.19, "score": 0.934},
    {"x": 0.58, "y": 0.11, "w": 0.24, "h": 0.19, "score": 0.908},
]
# Two vehicles → two number plates (proves multi-plate detection + per-plate evidence).
PLATE_BOXES = [
    {"x": 0.12, "y": 0.70, "w": 0.34, "h": 0.085, "text": PLATE_TEXT,
     "det_confidence": 0.93, "ocr_confidence": 0.88},
    {"x": 0.55, "y": 0.80, "w": 0.32, "h": 0.080, "text": PLATE_TEXT_2,
     "det_confidence": 0.84, "ocr_confidence": 0.71},
]


def _font(size: int):
    for p in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ):
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def _draw_face(d: ImageDraw.ImageDraw, box: dict, idx: int) -> None:
    x0, y0 = box["x"] * W, box["y"] * H
    x1, y1 = x0 + box["w"] * W, y0 + box["h"] * H
    cx = (x0 + x1) / 2
    # head
    d.ellipse([x0, y0, x1, y1], fill=(226, 190, 160), outline=(120, 95, 70), width=3)
    ew = box["w"] * W * 0.12
    eyeY = y0 + box["h"] * H * 0.38
    for off in (-box["w"] * W * 0.18, box["w"] * W * 0.18):
        d.ellipse([cx + off - ew, eyeY - ew, cx + off + ew, eyeY + ew], fill=(40, 40, 40))
    # mouth
    mY = y0 + box["h"] * H * 0.70
    d.arc([cx - box["w"] * W * 0.22, mY - 14, cx + box["w"] * W * 0.22, mY + 22], 20, 160, fill=(120, 60, 60), width=6)
    d.text((x0, y0 - 34), f"Person {idx}", font=_font(26), fill=(60, 60, 60))


def _draw_plate(d: ImageDraw.ImageDraw, box: dict) -> None:
    px0, py0 = box["x"] * W, box["y"] * H
    px1, py1 = px0 + box["w"] * W, py0 + box["h"] * H
    d.rounded_rectangle([px0, py0, px1, py1], radius=12, fill=(248, 222, 60), outline=(20, 20, 20), width=4)
    f = _font(int(box["h"] * H * 0.55))
    tb = d.textbbox((0, 0), box["text"], font=f)
    d.text(
        (px0 + (px1 - px0 - (tb[2] - tb[0])) / 2, py0 + (py1 - py0 - (tb[3] - tb[1])) / 2 - tb[1]),
        box["text"], font=f, fill=(15, 15, 15),
    )


def _make_image() -> bytes:
    img = Image.new("RGB", (W, H), (205, 212, 220))
    d = ImageDraw.Draw(img)
    # a simple "yard" backdrop
    d.rectangle([0, int(H * 0.52), W, H], fill=(150, 150, 150))
    d.rectangle([0, int(H * 0.52), W, int(H * 0.52) + 6], fill=(90, 90, 90))
    for b, i in zip(FACE_BOXES, (1, 2)):
        _draw_face(d, b, i)
    # two vehicle bodies behind the two plates
    d.rounded_rectangle([int(W * 0.06), int(H * 0.60), int(W * 0.49), int(H * 0.86)],
                        radius=24, fill=(44, 72, 120), outline=(20, 36, 70), width=4)
    d.rounded_rectangle([int(W * 0.51), int(H * 0.70), int(W * 0.93), int(H * 0.95)],
                        radius=24, fill=(96, 58, 58), outline=(50, 28, 28), width=4)
    for pb in PLATE_BOXES:
        _draw_plate(d, pb)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=88)
    return buf.getvalue()


async def main() -> None:
    storage = get_storage()
    photo_key = await storage.save(_make_image(), "jpg")

    async with SessionLocal() as s:
        # a demo worker (reporter) + their demo dept
        worker = (
            await s.execute(
                select(Employee).join(Role).where(
                    Employee.is_demo.is_(True), Role.rank >= 4,
                    Employee.department_code.isnot(None),
                ).limit(1)
            )
        ).scalar_one_or_none()
        if worker is None:
            print("No demo worker found — run scripts/seed_demo_cast.py first.")
            return
        dept = worker.department_code

        inc = (
            await s.execute(select(Incident).where(Incident.client_uuid == FIXTURE_UUID))
        ).scalar_one_or_none()
        if inc is None:
            inc = Incident(client_uuid=FIXTURE_UUID)
            s.add(inc)
        inc.reported_by = worker.id
        inc.department_code = dept
        inc.category = "other"
        inc.photo_key = photo_key
        inc.description = "Demo fixture: two people near a vehicle at the gate (face + plate evidence)."
        inc.status = "submitted"
        inc.severity = "normal"
        inc.detected_plate = PLATE_TEXT
        inc.plate_status = "detected"
        inc.plate_confidence = 88.0
        inc.plate_source = "local_onnx"
        inc.plate_reason = None
        inc.source = "field"
        inc.is_demo = True
        inc.is_demo_seed = False  # ephemeral demo row → hourly demo_cleanup auto-purges it
        await s.flush()

        # refresh analysis rows (idempotent per incident)
        old = (
            await s.execute(select(PhotoAnalysis).where(PhotoAnalysis.incident_id == inc.id))
        ).scalars().all()
        for a in old:
            await s.delete(a)
        await s.flush()

        pa = PhotoAnalysis(
            incident_id=inc.id, photo_key=photo_key, slot="primary", status="done",
            face_count=len(FACE_BOXES), plate_count=len(PLATE_BOXES), is_demo=True,
        )
        s.add(pa)
        await s.flush()
        for fb in FACE_BOXES:
            s.add(PhotoFace(analysis_id=pa.id, x=fb["x"], y=fb["y"], w=fb["w"], h=fb["h"], score=fb["score"]))
        for pb in PLATE_BOXES:
            s.add(PhotoPlate(
                analysis_id=pa.id, x=pb["x"], y=pb["y"], w=pb["w"], h=pb["h"],
                plate_text=pb["text"], original_text=pb["text"],
                det_confidence=pb["det_confidence"], ocr_confidence=pb["ocr_confidence"],
                region="MH", source="local_onnx",
            ))
        await s.commit()
        print(f"OK incident_id={inc.id} dept={dept} photo_key={photo_key}")
        print(f"   faces={len(FACE_BOXES)} plates={len(PLATE_BOXES)} "
              f"({', '.join(p['text'] for p in PLATE_BOXES)}) is_demo=true is_demo_seed=false "
              f"— visible to Demo CGM D500, AUTO-PURGED by hourly demo_cleanup")


if __name__ == "__main__":
    asyncio.run(main())
