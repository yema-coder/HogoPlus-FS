"""Prompt 7: video capture, password login (webdash), address_text polish.

Revision ID: 0005_video_password_polish
Revises: 0004_ux_pack
"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("employees", sa.Column("password_hash", sa.String(255), nullable=True))
    op.add_column(
        "employees",
        sa.Column("must_change_password", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("incidents", sa.Column("video_key", sa.String(500), nullable=True))
    op.add_column("incidents", sa.Column("address_text", sa.String(300), nullable=True))
    op.alter_column("incidents", "photo_key", existing_type=sa.String(500), nullable=True)
    op.add_column("form_submissions", sa.Column("address_text", sa.String(300), nullable=True))


def downgrade() -> None:
    op.drop_column("form_submissions", "address_text")
    op.alter_column("incidents", "photo_key", existing_type=sa.String(500), nullable=False)
    op.drop_column("incidents", "address_text")
    op.drop_column("incidents", "video_key")
    op.drop_column("employees", "must_change_password")
    op.drop_column("employees", "password_hash")
