"""Face REFERENCE data collection (Part D).

Adds:
  * settings.face_collection_enabled (bool, default FALSE) — the master switch; when
    OFF (the default) the attendance punch background job is a no-op.
  * face_references — one row per collected attendance-selfie face: the SFace 128-d
    embedding (nullable), the aligned crop key, a quality score, and the exact
    model/detector versions that produced it.

STRICTLY data collection — NO matching / identification is performed anywhere.

Chain note (fork/branch): this workspace's prior head is 0027 which chains after the
production-only 0026. Keep down_revision="0027" so it applies cleanly on production.
Requires the pgvector extension (already created by migration 0001).
"""
import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import UUID

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "settings",
        sa.Column(
            "face_collection_enabled", sa.Boolean(), nullable=False, server_default="false"
        ),
    )
    op.create_table(
        "face_references",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("employee_id", UUID(as_uuid=True), nullable=False),
        sa.Column("attendance_id", UUID(as_uuid=True), nullable=True),
        sa.Column("source", sa.String(length=20), nullable=False, server_default="attendance"),
        sa.Column("selfie_key", sa.String(length=500), nullable=True),
        sa.Column("crop_key", sa.String(length=500), nullable=True),
        sa.Column("embedding", Vector(128), nullable=True),
        sa.Column("embedding_dim", sa.Integer(), nullable=True),
        sa.Column("quality_score", sa.Float(), nullable=True),
        sa.Column("model_version", sa.String(length=40), nullable=False),
        sa.Column("det_version", sa.String(length=40), nullable=True),
        sa.Column("face_x", sa.Float(), nullable=True),
        sa.Column("face_y", sa.Float(), nullable=True),
        sa.Column("face_w", sa.Float(), nullable=True),
        sa.Column("face_h", sa.Float(), nullable=True),
        sa.Column("image_w", sa.Integer(), nullable=True),
        sa.Column("image_h", sa.Integer(), nullable=True),
        sa.Column("is_demo", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["employee_id"], ["employees.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["attendance_id"], ["attendance.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_face_references_employee_id", "face_references", ["employee_id"])
    op.create_index("ix_face_references_attendance_id", "face_references", ["attendance_id"])
    op.create_index("ix_face_references_is_demo", "face_references", ["is_demo"])


def downgrade() -> None:
    op.drop_index("ix_face_references_is_demo", table_name="face_references")
    op.drop_index("ix_face_references_attendance_id", table_name="face_references")
    op.drop_index("ix_face_references_employee_id", table_name="face_references")
    op.drop_table("face_references")
    op.drop_column("settings", "face_collection_enabled")
