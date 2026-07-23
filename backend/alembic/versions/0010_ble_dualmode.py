"""BLE dual-mode matching (MAC + iBeacon UUID/Major/Minor) + incident zone context.

Reuses the legacy ble_beacons.beacon_uuid/major/minor columns for iBeacon matching:
make them nullable, normalize existing MAC-only rows to NULL triples, and add a
uniqueness guard on (beacon_uuid, major, minor) so one Minor can't map to two zones.
Also adds nullable ble_beacon_id + ble_zone context columns to incidents.

Safe on existing Neon data: existing MAC-only rows keep working (their empty/zero
triple is normalized to NULL, and NULLs are distinct under the unique constraint).

Revision ID: 0010
Revises: 0009
"""
import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) make the legacy iBeacon columns nullable (reused for dual-mode matching)
    op.alter_column("ble_beacons", "beacon_uuid", existing_type=sa.String(100), nullable=True)
    op.alter_column("ble_beacons", "major", existing_type=sa.Integer(), nullable=True)
    op.alter_column("ble_beacons", "minor", existing_type=sa.Integer(), nullable=True)

    # 2) normalize existing MAC-only rows: blank/zero triple -> NULL so the unique
    #    guard treats them as distinct (multiple MAC beacons allowed).
    op.execute(
        "UPDATE ble_beacons SET beacon_uuid = NULL "
        "WHERE beacon_uuid IS NOT NULL AND btrim(beacon_uuid) = ''"
    )
    op.execute(
        "UPDATE ble_beacons SET major = NULL, minor = NULL "
        "WHERE beacon_uuid IS NULL"
    )

    # 3) uniqueness guard on the iBeacon triple
    op.create_unique_constraint(
        "uq_ble_beacons_ibeacon", "ble_beacons", ["beacon_uuid", "major", "minor"]
    )

    # 4) incident BLE zone context (non-verification)
    op.add_column("incidents", sa.Column("ble_beacon_id", sa.String(100), nullable=True))
    op.add_column("incidents", sa.Column("ble_zone", sa.String(100), nullable=True))


def downgrade() -> None:
    op.drop_column("incidents", "ble_zone")
    op.drop_column("incidents", "ble_beacon_id")
    op.drop_constraint("uq_ble_beacons_ibeacon", "ble_beacons", type_="unique")
    op.execute("UPDATE ble_beacons SET beacon_uuid = '' WHERE beacon_uuid IS NULL")
    op.execute("UPDATE ble_beacons SET major = 0 WHERE major IS NULL")
    op.execute("UPDATE ble_beacons SET minor = 0 WHERE minor IS NULL")
    op.alter_column("ble_beacons", "minor", existing_type=sa.Integer(), nullable=False)
    op.alter_column("ble_beacons", "major", existing_type=sa.Integer(), nullable=False)
    op.alter_column("ble_beacons", "beacon_uuid", existing_type=sa.String(100), nullable=False)
