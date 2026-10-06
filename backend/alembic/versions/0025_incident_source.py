"""Incident capture source (field vs gallery).

Adds incidents.source — 'field' for normal in-app camera/video captures (the
default for every existing and future real report) and 'gallery' for test
uploads chosen from the photo library by an AR-debug allowlisted account.
Gallery captures are routed/analysed like normal complaints but are excluded
from factory statistics (KPI counts, pending/aging) so test data never skews
the real numbers. Additive, NOT NULL with a server default so existing rows
backfill to 'field'.
"""
import sqlalchemy as sa
from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "incidents",
        sa.Column("source", sa.String(length=10), nullable=False, server_default="field"),
    )


def downgrade() -> None:
    op.drop_column("incidents", "source")
