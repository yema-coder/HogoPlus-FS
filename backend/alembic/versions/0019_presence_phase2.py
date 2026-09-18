"""v1.0.26: LIVE PRESENCE Phase 2 — alerts engine (additive only).

presence_alerts: one OPEN row per (employee, alert_type), raised/refreshed/
auto-resolved by the minute sweep, ack/resolve by managers.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "presence_alerts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("employee_id", UUID(as_uuid=True), sa.ForeignKey("employees.id"), nullable=False),
        sa.Column("alert_type", sa.String(30), nullable=False),
        sa.Column("status", sa.String(15), nullable=False, server_default="active"),
        sa.Column("zone_key", sa.String(150), nullable=True),
        sa.Column("zone_en", sa.String(100), nullable=True),
        sa.Column("detail", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("acknowledged_by", UUID(as_uuid=True), sa.ForeignKey("employees.id"), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by", UUID(as_uuid=True), sa.ForeignKey("employees.id"), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_demo", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_presence_alerts_employee_id", "presence_alerts", ["employee_id"])
    op.create_index("ix_presence_alerts_status", "presence_alerts", ["status"])
    op.create_index("ix_presence_alerts_is_demo", "presence_alerts", ["is_demo"])


def downgrade() -> None:
    op.drop_table("presence_alerts")
