"""Step 3 camera AI: on-device distance persistence + backend face/plate analysis.

- incidents: distance_m / distance_method / distance_confidence / distance_uncertainty_m
- settings: ar_distance_enabled / face_detection_enabled / plate_detection_enabled (all ON)
- photo_analyses + photo_faces + photo_plates (local ONNX detections, editable plates)
All additive.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("incidents", sa.Column("distance_m", sa.Float(), nullable=True))
    op.add_column("incidents", sa.Column("distance_method", sa.String(20), nullable=True))
    op.add_column("incidents", sa.Column("distance_confidence", sa.String(10), nullable=True))
    op.add_column("incidents", sa.Column("distance_uncertainty_m", sa.Float(), nullable=True))

    op.add_column(
        "settings",
        sa.Column("ar_distance_enabled", sa.Boolean(), nullable=False, server_default="true"),
    )
    op.add_column(
        "settings",
        sa.Column("face_detection_enabled", sa.Boolean(), nullable=False, server_default="true"),
    )
    op.add_column(
        "settings",
        sa.Column("plate_detection_enabled", sa.Boolean(), nullable=False, server_default="true"),
    )

    op.create_table(
        "photo_analyses",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "incident_id", UUID(as_uuid=True),
            sa.ForeignKey("incidents.id", ondelete="CASCADE"), nullable=True,
        ),
        sa.Column(
            "submission_id", UUID(as_uuid=True),
            sa.ForeignKey("form_submissions.id", ondelete="CASCADE"), nullable=True,
        ),
        sa.Column("photo_key", sa.String(500), nullable=False),
        sa.Column("slot", sa.String(20), nullable=False, server_default="primary"),
        sa.Column("status", sa.String(15), nullable=False, server_default="pending"),
        sa.Column("face_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("plate_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.String(200), nullable=True),
        sa.Column("is_demo", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("incident_id", "photo_key", name="uq_photo_analysis_incident_key"),
    )
    op.create_index("ix_photo_analyses_incident_id", "photo_analyses", ["incident_id"])
    op.create_index("ix_photo_analyses_submission_id", "photo_analyses", ["submission_id"])
    op.create_index("ix_photo_analyses_is_demo", "photo_analyses", ["is_demo"])

    op.create_table(
        "photo_faces",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "analysis_id", UUID(as_uuid=True),
            sa.ForeignKey("photo_analyses.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("x", sa.Float(), nullable=False),
        sa.Column("y", sa.Float(), nullable=False),
        sa.Column("w", sa.Float(), nullable=False),
        sa.Column("h", sa.Float(), nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_photo_faces_analysis_id", "photo_faces", ["analysis_id"])

    op.create_table(
        "photo_plates",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "analysis_id", UUID(as_uuid=True),
            sa.ForeignKey("photo_analyses.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("x", sa.Float(), nullable=False),
        sa.Column("y", sa.Float(), nullable=False),
        sa.Column("w", sa.Float(), nullable=False),
        sa.Column("h", sa.Float(), nullable=False),
        sa.Column("plate_text", sa.String(20), nullable=True),
        sa.Column("det_confidence", sa.Float(), nullable=True),
        sa.Column("ocr_confidence", sa.Float(), nullable=True),
        sa.Column("region", sa.String(40), nullable=True),
        sa.Column("source", sa.String(20), nullable=False, server_default="local_onnx"),
        sa.Column("edited", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("edited_by", UUID(as_uuid=True), sa.ForeignKey("employees.id"), nullable=True),
        sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_photo_plates_analysis_id", "photo_plates", ["analysis_id"])


def downgrade() -> None:
    op.drop_table("photo_plates")
    op.drop_table("photo_faces")
    op.drop_table("photo_analyses")
    op.drop_column("settings", "plate_detection_enabled")
    op.drop_column("settings", "face_detection_enabled")
    op.drop_column("settings", "ar_distance_enabled")
    op.drop_column("incidents", "distance_uncertainty_m")
    op.drop_column("incidents", "distance_confidence")
    op.drop_column("incidents", "distance_method")
    op.drop_column("incidents", "distance_m")
