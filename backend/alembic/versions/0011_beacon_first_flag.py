"""Beacon-first policy feature flag (Task B) — ships OFF.

Adds settings.beacon_first_mode (boolean, NOT NULL, default false). With the flag
OFF behavior is byte-identical to the launch BEACON-WINS ladder. With the flag ON:
beacon zone = primary location identity; GPS stored as secondary evidence only;
no-beacon punches are ACCEPTED but flagged (no_beacon_gps_only / no_beacon_no_gps).

Revision ID: 0011
Revises: 0010
"""
import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "settings",
        sa.Column("beacon_first_mode", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("settings", "beacon_first_mode")
