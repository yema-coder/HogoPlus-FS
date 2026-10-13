"""Attendance verification ladder + per-punch location + auto punch-out (2026-06).

Additive-only. Adds:
  settings:
    * gps_verify_enabled          bool  default FALSE  (GPS as a valid 2nd path; ships OFF)
    * gps_accuracy_max_m          int   default 100
    * geofence_grace_m            int   default 150
    * auto_punch_out_enabled      bool  default FALSE  (ships OFF)
    * auto_punch_out_grace_min    int   default 60
  attendance:
    * gps_accuracy        float   (reported device accuracy radius, m)
    * geo_distance_m      float   (straight-line distance from factory centre, m)
    * verification_path   varchar(10)  ('beacon' | 'gps' | NULL)
    * geo_address         varchar(300) (device reverse-geocoded address)
    * punch_out_source    varchar(10)  ('manual' | 'auto' | NULL)

Chain: down_revision=0028 (→ 0027 → 0026 on production).
"""
import sqlalchemy as sa
from alembic import op

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("settings", sa.Column("gps_verify_enabled", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("settings", sa.Column("gps_accuracy_max_m", sa.Integer(), nullable=False, server_default="100"))
    op.add_column("settings", sa.Column("geofence_grace_m", sa.Integer(), nullable=False, server_default="150"))
    op.add_column("settings", sa.Column("auto_punch_out_enabled", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("settings", sa.Column("auto_punch_out_grace_min", sa.Integer(), nullable=False, server_default="60"))

    op.add_column("attendance", sa.Column("gps_accuracy", sa.Float(), nullable=True))
    op.add_column("attendance", sa.Column("geo_distance_m", sa.Float(), nullable=True))
    op.add_column("attendance", sa.Column("verification_path", sa.String(length=10), nullable=True))
    op.add_column("attendance", sa.Column("geo_address", sa.String(length=300), nullable=True))
    op.add_column("attendance", sa.Column("punch_out_source", sa.String(length=10), nullable=True))


def downgrade() -> None:
    op.drop_column("attendance", "punch_out_source")
    op.drop_column("attendance", "geo_address")
    op.drop_column("attendance", "verification_path")
    op.drop_column("attendance", "geo_distance_m")
    op.drop_column("attendance", "gps_accuracy")
    op.drop_column("settings", "auto_punch_out_grace_min")
    op.drop_column("settings", "auto_punch_out_enabled")
    op.drop_column("settings", "geofence_grace_m")
    op.drop_column("settings", "gps_accuracy_max_m")
    op.drop_column("settings", "gps_verify_enabled")
