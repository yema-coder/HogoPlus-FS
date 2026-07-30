"""v1.0.21 P1 batch: attendance regularization requests, duplicate-incident
clustering (display-only, rules tunable in settings), all additive/inert.

Revision ID: 0015
Revises: 0014
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # -- duplicate clustering (display-only grouping) --------------------------
    op.add_column(
        "incidents",
        sa.Column(
            "duplicate_of", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("incidents.id"), nullable=True,
        ),
    )
    op.create_index("ix_incidents_duplicate_of", "incidents", ["duplicate_of"])
    # tunable rules — no deploy needed to change them
    op.add_column("settings", sa.Column("dup_window_minutes", sa.Integer(), nullable=False, server_default="30"))
    op.add_column("settings", sa.Column("dup_same_zone", sa.Boolean(), nullable=False, server_default="true"))
    op.add_column("settings", sa.Column("dup_same_category", sa.Boolean(), nullable=False, server_default="true"))

    # -- attendance regularization requests ------------------------------------
    op.create_table(
        "attendance_regularizations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("attendance_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("attendance.id"), nullable=False),
        sa.Column("employee_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("employees.id"), nullable=False),
        sa.Column("text_note", sa.String(500), nullable=True),
        sa.Column("voice_note_key", sa.String(500), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        sa.Column("reviewed_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("employees.id"), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_note", sa.String(500), nullable=True),
        sa.Column("is_demo", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_att_reg_attendance", "attendance_regularizations", ["attendance_id"])
    op.create_index("ix_att_reg_employee", "attendance_regularizations", ["employee_id"])
    op.create_index("ix_att_reg_is_demo", "attendance_regularizations", ["is_demo"])
    # ONE open request per punch — enforced at the database level (no spam)
    op.create_index(
        "uq_att_reg_open", "attendance_regularizations", ["attendance_id"],
        unique=True, postgresql_where=sa.text("status = 'open'"),
    )


def downgrade() -> None:
    op.drop_table("attendance_regularizations")
    op.drop_column("settings", "dup_same_category")
    op.drop_column("settings", "dup_same_zone")
    op.drop_column("settings", "dup_window_minutes")
    op.drop_index("ix_incidents_duplicate_of", table_name="incidents")
    op.drop_column("incidents", "duplicate_of")
