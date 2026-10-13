"""Preserve the model's original plate read (photo_plates.original_text).

When a reviewer corrects a detected number plate, plate_text is overwritten with
the hand-entered value. This adds original_text to keep the model's FIRST read so
the app and dashboard can show "CORRECTED (model read: XYZ)" beside the correction.
Set once at analysis time; never auto-overwritten. Additive + nullable.

NOTE (fork/branch): this workspace's alembic head is 0025, but the production DB is
already at 0026 (a revision merged into main / PR #28 that is not in this workspace).
This migration therefore chains after 0026 so it applies cleanly on production. If
the deploy pipeline reports a missing/own head, re-point down_revision to the current
production head before `alembic upgrade head`.
"""
import sqlalchemy as sa
from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "photo_plates",
        sa.Column("original_text", sa.String(length=20), nullable=True),
    )
    # backfill: existing rows that were never edited — their current text IS the read
    op.execute(
        "UPDATE photo_plates SET original_text = plate_text "
        "WHERE original_text IS NULL AND edited = false"
    )


def downgrade() -> None:
    op.drop_column("photo_plates", "original_text")
