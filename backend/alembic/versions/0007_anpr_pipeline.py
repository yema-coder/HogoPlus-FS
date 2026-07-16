"""Prompt 9: ANPR pipeline hardening — plate status/confidence/source/reason on incidents.

Revision ID: 0007_anpr_pipeline
Revises: 0006_ble_mac
"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("incidents", sa.Column("plate_status", sa.String(20), nullable=True))
    op.add_column("incidents", sa.Column("plate_confidence", sa.Float(), nullable=True))
    op.add_column("incidents", sa.Column("plate_source", sa.String(20), nullable=True))
    op.add_column("incidents", sa.Column("plate_reason", sa.String(200), nullable=True))
    # legacy rows that already have a plate were detected via Rekognition
    op.execute(
        "UPDATE incidents SET plate_status='detected', plate_source='rekognition' "
        "WHERE detected_plate IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_column("incidents", "plate_reason")
    op.drop_column("incidents", "plate_source")
    op.drop_column("incidents", "plate_confidence")
    op.drop_column("incidents", "plate_status")
