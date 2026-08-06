"""v1.0.24: per-department policy flags + shared MD access.

departments: beacon_exempt / geofence_exempt / can_add_employees
settings:    md_password_hash (shared MD dashboard password) / md_otp_phones
"""
import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "departments",
        sa.Column("beacon_exempt", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "departments",
        sa.Column("geofence_exempt", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "departments",
        sa.Column("can_add_employees", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column("settings", sa.Column("md_password_hash", sa.String(255), nullable=True))
    op.add_column(
        "settings",
        sa.Column("md_otp_phones", sa.String(200), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("settings", "md_otp_phones")
    op.drop_column("settings", "md_password_hash")
    op.drop_column("departments", "can_add_employees")
    op.drop_column("departments", "geofence_exempt")
    op.drop_column("departments", "beacon_exempt")
