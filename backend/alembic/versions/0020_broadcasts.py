"""v1.0.27: Broadcast / Send-Notification engine (additive only).

- broadcasts: one composed push to a resolved audience + rolled-up delivery counts.
- broadcast_receipts: per-recipient tracking (delivery report, resend-to-failed,
  Expo receipt polling, invalid-token cleanup).
- settings: broadcasts_enabled (flag, OFF) + broadcast_rate_per_hour (10).
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "settings",
        sa.Column("broadcasts_enabled", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "settings",
        sa.Column("broadcast_rate_per_hour", sa.Integer(), nullable=False, server_default="10"),
    )

    op.create_table(
        "broadcasts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("employees.id"), nullable=False),
        sa.Column("audience_type", sa.String(20), nullable=False),
        sa.Column("audience_json", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("title_en", sa.String(200), nullable=False, server_default=""),
        sa.Column("title_hi", sa.String(200), nullable=False, server_default=""),
        sa.Column("title_mr", sa.String(200), nullable=False, server_default=""),
        sa.Column("body_en", sa.Text(), nullable=False, server_default=""),
        sa.Column("body_hi", sa.Text(), nullable=False, server_default=""),
        sa.Column("body_mr", sa.Text(), nullable=False, server_default=""),
        sa.Column("priority", sa.String(12), nullable=False, server_default="normal"),
        sa.Column("deep_link_type", sa.String(20), nullable=True),
        sa.Column("deep_link_id", sa.String(60), nullable=True),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(15), nullable=False, server_default="sent"),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recipient_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("installed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sent_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("delivered_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("no_token_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("suppressed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("opened_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_test", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("is_demo", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_broadcasts_created_by", "broadcasts", ["created_by"])
    op.create_index("ix_broadcasts_status", "broadcasts", ["status"])
    op.create_index("ix_broadcasts_is_demo", "broadcasts", ["is_demo"])

    op.create_table(
        "broadcast_receipts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "broadcast_id", UUID(as_uuid=True),
            sa.ForeignKey("broadcasts.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("employee_id", UUID(as_uuid=True), sa.ForeignKey("employees.id"), nullable=False),
        sa.Column("notification_id", UUID(as_uuid=True), nullable=True),
        sa.Column("ticket_id", sa.String(120), nullable=True),
        sa.Column("status", sa.String(15), nullable=False, server_default="queued"),
        sa.Column("error", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_broadcast_receipts_broadcast_id", "broadcast_receipts", ["broadcast_id"])
    op.create_index("ix_broadcast_receipts_employee_id", "broadcast_receipts", ["employee_id"])
    op.create_index("ix_broadcast_receipts_status", "broadcast_receipts", ["status"])


def downgrade() -> None:
    op.drop_table("broadcast_receipts")
    op.drop_table("broadcasts")
    op.drop_column("settings", "broadcast_rate_per_hour")
    op.drop_column("settings", "broadcasts_enabled")
