"""Dual-mode BLE beacon resolution (MAC or iBeacon UUID/Major/Minor).

Shared by attendance punch-in (drives verified_plus) and incident capture
(zone context only). A scanned device matches a registered beacon if EITHER
its MAC equals a registered mac_address (case-insensitive) OR its
(UUID, Major, Minor) equals a registered (beacon_uuid, major, minor) triple
(UUID case-insensitive). Only ACTIVE registered beacons match — unregistered
or inactive beacons resolve to None (ignored, never blocks a punch/capture).
"""
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import BleBeacon


async def resolve_beacon(
    session: AsyncSession,
    *,
    mac: str | None = None,
    ibeacon_uuid: str | None = None,
    major: int | None = None,
    minor: int | None = None,
) -> BleBeacon | None:
    """Return the ACTIVE registered beacon matching the incoming identifier, else None."""
    mac_norm = mac.strip().upper() if mac else None
    if mac_norm:
        beacon = (
            await session.execute(
                select(BleBeacon).where(
                    BleBeacon.mac_address == mac_norm, BleBeacon.is_active.is_(True)
                )
            )
        ).scalar_one_or_none()
        if beacon is not None:
            return beacon

    if ibeacon_uuid and major is not None and minor is not None:
        beacon = (
            await session.execute(
                select(BleBeacon).where(
                    func.lower(BleBeacon.beacon_uuid) == ibeacon_uuid.strip().lower(),
                    BleBeacon.major == major,
                    BleBeacon.minor == minor,
                    BleBeacon.is_active.is_(True),
                )
            )
        ).scalar_one_or_none()
        if beacon is not None:
            return beacon
    return None


def beacon_ref(
    *,
    mac: str | None = None,
    ibeacon_uuid: str | None = None,
    major: int | None = None,
    minor: int | None = None,
) -> str | None:
    """Canonical identifier string stored on the record for audit/context.
    MAC mode -> uppercased MAC; iBeacon mode -> "ibeacon:<uuid>:<major>:<minor>"."""
    if mac:
        return mac.strip().upper()
    if ibeacon_uuid and major is not None and minor is not None:
        return f"ibeacon:{ibeacon_uuid.strip().lower()}:{major}:{minor}"
    return None
