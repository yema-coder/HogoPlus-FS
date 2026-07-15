"""UX pack: AI routing suggestions, resolution photo, detected plates, dept-less registration.

Revision ID: 0004
Revises: 0003
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("incidents", sa.Column("ai_suggested_category", sa.String(40), nullable=True))
    op.add_column("incidents", sa.Column("ai_suggested_department", sa.String(30), nullable=True))
    op.add_column("incidents", sa.Column("ai_suggested_severity", sa.String(20), nullable=True))
    op.add_column("incidents", sa.Column("ai_confidence", sa.Float(), nullable=True))
    op.add_column("incidents", sa.Column("ai_confirmed_by", sa.String(20), nullable=True))
    op.add_column("incidents", sa.Column("ai_suggested_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("incidents", sa.Column("detected_plate", sa.String(20), nullable=True))
    op.add_column("incidents", sa.Column("resolution_photo_key", sa.String(500), nullable=True))
    op.add_column("form_submissions", sa.Column("detected_plates", JSONB(), nullable=True))
    op.alter_column("employees", "department_code", existing_type=sa.String(30), nullable=True)


def downgrade() -> None:
    op.alter_column("employees", "department_code", existing_type=sa.String(30), nullable=False)
    op.drop_column("form_submissions", "detected_plates")
    for col in (
        "resolution_photo_key", "detected_plate", "ai_suggested_at", "ai_confirmed_by",
        "ai_confidence", "ai_suggested_severity", "ai_suggested_department", "ai_suggested_category",
    ):
        op.drop_column("incidents", col)
