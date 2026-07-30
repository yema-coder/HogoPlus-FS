"""v1.0.20 batch: registration context for approvals (who/where/when evidence)
+ bilingual (Marathi + English) AI incident assessment. All additive/inert.

Revision ID: 0014
Revises: 0013
"""
import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # -- registration evidence captured at self-registration time -------------
    op.add_column("employees", sa.Column("reg_lat", sa.Float(), nullable=True))
    op.add_column("employees", sa.Column("reg_lng", sa.Float(), nullable=True))
    op.add_column("employees", sa.Column("reg_address", sa.String(300), nullable=True))
    op.add_column("employees", sa.Column("reg_zone", sa.String(120), nullable=True))
    op.add_column("employees", sa.Column("reg_inside_geofence", sa.Boolean(), nullable=True))
    op.add_column("employees", sa.Column("reg_device", sa.String(120), nullable=True))
    op.add_column("employees", sa.Column("reg_app_version", sa.String(20), nullable=True))
    op.add_column("employees", sa.Column("reg_face_count", sa.Integer(), nullable=True))
    # -- Marathi half of the AI assessment ------------------------------------
    op.add_column("incidents", sa.Column("severity_reason_mr", sa.String(300), nullable=True))


def downgrade() -> None:
    op.drop_column("incidents", "severity_reason_mr")
    for col in ("reg_face_count", "reg_app_version", "reg_device", "reg_inside_geofence",
                "reg_zone", "reg_address", "reg_lng", "reg_lat"):
        op.drop_column("employees", col)
