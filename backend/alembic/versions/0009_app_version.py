"""Prompt 16: app_versions table for the mobile update-available banner.

Revision ID: 0009_app_version
Revises: 0008_demo_isolation
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "app_versions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("latest_version", sa.String(20), nullable=False),
        sa.Column("apk_url", sa.String(500), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("app_versions")
