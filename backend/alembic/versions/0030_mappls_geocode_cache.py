"""Mappls geocode cache + incident GPS accuracy (2026-06).

Additive-only. Adds:
  * geocode_cache          — server-side reverse-geocode cache (Mappls), unique on coords.
  * incidents.gps_accuracy — device GPS accuracy (m) captured with the incident photo.

Chain: down_revision=0029 (→ 0028 → 0027 → 0026 on production).
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("incidents", sa.Column("gps_accuracy", sa.Float(), nullable=True))
    op.create_table(
        "geocode_cache",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("lat_key", sa.Float(), nullable=False),
        sa.Column("lng_key", sa.Float(), nullable=False),
        sa.Column("address", sa.String(length=300), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("lat_key", "lng_key", name="uq_geocode_cache_coords"),
    )


def downgrade() -> None:
    op.drop_table("geocode_cache")
    op.drop_column("incidents", "gps_accuracy")
