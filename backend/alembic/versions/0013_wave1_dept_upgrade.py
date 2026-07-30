"""Wave 1 dept upgrade: config-driven home layouts + Security vehicle entry/exit
log + notification anti-spam flag. All additive; feature flags default OFF so the
deploy is inert for real users until flipped (demo bubble bypasses the flags).

Revision ID: 0013
Revises: 0012
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "settings",
        sa.Column("home_config_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "settings",
        sa.Column("vehicle_log_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "settings",
        sa.Column("notif_batching_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    op.create_table(
        "home_configs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("department_code", sa.String(30), sa.ForeignKey("departments.code"), nullable=True),
        sa.Column("role_code", sa.String(20), sa.ForeignKey("roles.code"), nullable=True),
        sa.Column("config_json", JSONB, nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("department_code", "role_code", name="uq_home_config_dept_role"),
    )

    op.create_table(
        "vehicle_logs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("plate", sa.String(20), nullable=False, index=True),
        sa.Column("vehicle_type", sa.String(20), nullable=False),
        sa.Column("direction", sa.String(3), nullable=False),
        sa.Column("driver_name", sa.String(100), nullable=True),
        sa.Column("purpose", sa.String(100), nullable=True),
        sa.Column("photo_key", sa.String(500), nullable=True),
        sa.Column("voice_note_key", sa.String(500), nullable=True),
        sa.Column("gate_zone", sa.String(100), nullable=True),
        sa.Column("anpr_used", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("logged_by", UUID(as_uuid=True), sa.ForeignKey("employees.id"), nullable=False),
        sa.Column("paired_log_id", UUID(as_uuid=True), sa.ForeignKey("vehicle_logs.id"), nullable=True),
        sa.Column("client_uuid", sa.String(64), nullable=True, unique=True),
        sa.Column("is_demo", sa.Boolean(), nullable=False, server_default=sa.false(), index=True),
        sa.Column("logged_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_vehicle_logs_plate_dir", "vehicle_logs", ["plate", "direction", "logged_at"])
    op.create_index("ix_vehicle_logs_logged_at", "vehicle_logs", ["logged_at"])


def downgrade() -> None:
    op.drop_table("vehicle_logs")
    op.drop_table("home_configs")
    op.drop_column("settings", "notif_batching_enabled")
    op.drop_column("settings", "vehicle_log_enabled")
    op.drop_column("settings", "home_config_enabled")
