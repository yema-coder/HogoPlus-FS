"""Record which rotation produced the detections.

The AR camera writes its JPEG in sensor orientation, so a portrait photo reaches
the server as landscape and face detection finds nothing. The analysis now retries
at 90°/270° and stores the rotation that worked — non-zero means the STORED image
is mis-rotated and a viewer should rotate it to display it upright. Additive,
NOT NULL with a server default, so existing rows backfill to 0.
"""
import sqlalchemy as sa
from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "photo_analyses",
        sa.Column("rotation_deg", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("photo_analyses", "rotation_deg")
