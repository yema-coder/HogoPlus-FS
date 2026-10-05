"""Step 5 plate-scale cross-check settings."""
import sqlalchemy as sa
from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "settings",
        sa.Column("plate_scale_enabled", sa.Boolean(), nullable=False, server_default="true"),
    )
    op.add_column(
        "settings",
        sa.Column("plate_ref_width_m", sa.Float(), nullable=False, server_default="0.5"),
    )
    op.add_column(
        "settings",
        sa.Column("plate_scale_k", sa.Float(), nullable=False, server_default="1.2"),
    )


def downgrade() -> None:
    op.drop_column("settings", "plate_scale_k")
    op.drop_column("settings", "plate_ref_width_m")
    op.drop_column("settings", "plate_scale_enabled")
