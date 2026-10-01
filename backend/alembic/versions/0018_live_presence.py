"""v1.0.25: LIVE WORKER PRESENCE Phase 1 (additive only, flag-gated OFF).

worker_presence (latest state) / presence_history (30-day trail) /
presence_consents (versioned DPDP consent) + settings pilot/threshold columns.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "worker_presence",
        sa.Column("employee_id", UUID(as_uuid=True), sa.ForeignKey("employees.id"), primary_key=True),
        sa.Column("source", sa.String(10), nullable=False),
        sa.Column("zone_key", sa.String(150), nullable=True),
        sa.Column("zone_en", sa.String(100), nullable=True),
        sa.Column("zone_hi", sa.String(100), nullable=True),
        sa.Column("zone_mr", sa.String(100), nullable=True),
        sa.Column("zone_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lat", sa.Float(), nullable=True),
        sa.Column("lng", sa.Float(), nullable=True),
        sa.Column("accuracy_m", sa.Float(), nullable=True),
        sa.Column("inside_geofence", sa.Boolean(), nullable=True),
        sa.Column("battery_pct", sa.Integer(), nullable=True),
        sa.Column("app_version", sa.String(20), nullable=True),
        sa.Column("client_ts", sa.DateTime(timezone=True), nullable=True),
        sa.Column("server_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_demo", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_worker_presence_server_ts", "worker_presence", ["server_ts"])
    op.create_index("ix_worker_presence_is_demo", "worker_presence", ["is_demo"])

    op.create_table(
        "presence_history",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("employee_id", UUID(as_uuid=True), sa.ForeignKey("employees.id"), nullable=False),
        sa.Column("source", sa.String(10), nullable=False),
        sa.Column("zone_key", sa.String(150), nullable=True),
        sa.Column("zone_en", sa.String(100), nullable=True),
        sa.Column("lat", sa.Float(), nullable=True),
        sa.Column("lng", sa.Float(), nullable=True),
        sa.Column("accuracy_m", sa.Float(), nullable=True),
        sa.Column("inside_geofence", sa.Boolean(), nullable=True),
        sa.Column("battery_pct", sa.Integer(), nullable=True),
        sa.Column("client_ts", sa.DateTime(timezone=True), nullable=True),
        sa.Column("server_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_demo", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.create_index("ix_presence_history_employee_id", "presence_history", ["employee_id"])
    op.create_index("ix_presence_history_server_ts", "presence_history", ["server_ts"])
    op.create_index("ix_presence_history_is_demo", "presence_history", ["is_demo"])

    op.create_table(
        "presence_consents",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("employee_id", UUID(as_uuid=True), sa.ForeignKey("employees.id"), nullable=False),
        sa.Column("version", sa.String(10), nullable=False),
        sa.Column("lang", sa.String(5), nullable=False, server_default="mr"),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_presence_consents_employee_id", "presence_consents", ["employee_id"])

    op.add_column("settings", sa.Column("live_presence_enabled", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("settings", sa.Column("presence_pilot_emp_ids", sa.Text(), nullable=False, server_default=""))
    op.add_column("settings", sa.Column("presence_nosignal_alert_min", sa.Integer(), nullable=False, server_default="15"))
    op.add_column("settings", sa.Column("presence_outside_alert_min", sa.Integer(), nullable=False, server_default="10"))


def downgrade() -> None:
    op.drop_column("settings", "presence_outside_alert_min")
    op.drop_column("settings", "presence_nosignal_alert_min")
    op.drop_column("settings", "presence_pilot_emp_ids")
    op.drop_column("settings", "live_presence_enabled")
    op.drop_table("presence_consents")
    op.drop_table("presence_history")
    op.drop_table("worker_presence")
