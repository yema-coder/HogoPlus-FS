"""AR debug allowlist (additive, nullable→default empty).

Adds settings.ar_debug_emp_ids — a comma/newline-separated allowlist of employee
IDs and/or phone numbers for whom the on-device AR debug HUD + reprojection dot
is shown, WITHOUT an app rebuild. Default empty (nobody). Real workers never match.
"""
import sqlalchemy as sa
from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "settings",
        sa.Column("ar_debug_emp_ids", sa.Text(), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("settings", "ar_debug_emp_ids")
