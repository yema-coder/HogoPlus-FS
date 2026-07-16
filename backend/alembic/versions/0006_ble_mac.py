"""BLE vendor beacons: unique nullable MAC address for MAC-based matching.

Revision ID: 0006_ble_mac
Revises: 0005_video_password_polish
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ble_beacons", sa.Column("mac_address", sa.String(17), nullable=True))
    op.create_unique_constraint("uq_ble_beacons_mac_address", "ble_beacons", ["mac_address"])


def downgrade() -> None:
    op.drop_constraint("uq_ble_beacons_mac_address", "ble_beacons", type_="unique")
    op.drop_column("ble_beacons", "mac_address")
