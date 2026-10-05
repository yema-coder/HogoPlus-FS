"""Broadcast Quick Templates (additive only).

- broadcast_templates: reusable trilingual message templates a manager saves for
  the Broadcast composer. Built-in factory templates are served from code and are
  NOT stored here. Bubble-scoped via is_demo.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "broadcast_templates",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("employees.id"), nullable=False),
        sa.Column("title_en", sa.String(200), nullable=False, server_default=""),
        sa.Column("title_hi", sa.String(200), nullable=False, server_default=""),
        sa.Column("title_mr", sa.String(200), nullable=False, server_default=""),
        sa.Column("body_en", sa.Text(), nullable=False, server_default=""),
        sa.Column("body_hi", sa.Text(), nullable=False, server_default=""),
        sa.Column("body_mr", sa.Text(), nullable=False, server_default=""),
        sa.Column("priority", sa.String(12), nullable=False, server_default="normal"),
        sa.Column("is_demo", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_broadcast_templates_created_by", "broadcast_templates", ["created_by"])
    op.create_index("ix_broadcast_templates_is_demo", "broadcast_templates", ["is_demo"])


def downgrade() -> None:
    op.drop_table("broadcast_templates")
