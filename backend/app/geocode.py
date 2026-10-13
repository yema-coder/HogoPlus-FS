"""Server-side reverse geocoding for attendance/incident coordinates.

WHY SERVER-SIDE: the worker's phone must never be asked to resolve an address for
a record a MANAGER is reading — that would leak the lookup to the worker's network
and burn their data. The server resolves it once, caches it, and every later
viewer gets the cached string.

PRIVACY: a reverse lookup sends ONE pair of coordinates to OpenStreetMap's public
Nominatim service. No employee id, no name, nothing that identifies the person.
This is the same service and the same practice already used for registration
approvals (owner-approved 2026-10-13). Coordinates are rounded to 4 decimals
(~11 m) before they leave the box, which is also what makes the cache effective.

RATE LIMIT: Nominatim's usage policy allows at most 1 request/second from one
application and requires an identifying User-Agent. This module enforces both,
and NEVER runs in the punch-in path — only when a manager opens a record.
"""
from __future__ import annotations

import asyncio
import logging
import time

from app.redis_client import redis_client

logger = logging.getLogger("hogo.geocode")

NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"
USER_AGENT = "HogoPlus-FS/1.0 (factory ops; contact: ops@hogoplus.in)"
CACHE_PREFIX = "geo:rev:"
CACHE_TTL_SECONDS = 30 * 24 * 3600  # an address does not move
REQUEST_TIMEOUT = 6.0
MIN_INTERVAL_SECONDS = 1.1  # Nominatim policy: <= 1 req/s

_last_call = 0.0
_lock = asyncio.Lock()


def cache_key(lat: float, lng: float) -> str:
    """4 decimals ~= 11 m: enough to name a place, coarse enough that punches from
    the same spot on different days share one cache entry (and one lookup)."""
    return f"{CACHE_PREFIX}{lat:.4f},{lng:.4f}"


def _short_address(data: dict) -> str | None:
    """Nominatim's display_name is long and repetitive ("Plot 4, Ward 7, ...,
    India"). Build something a manager can read at a glance, nearest-first."""
    addr = data.get("address") or {}
    parts = [
        addr.get("village") or addr.get("hamlet") or addr.get("suburb") or addr.get("town"),
        addr.get("city") or addr.get("municipality"),
        addr.get("county") or addr.get("state_district"),
        addr.get("state"),
    ]
    seen: list[str] = []
    for p in parts:
        if p and p not in seen:
            seen.append(p)
    if seen:
        return ", ".join(seen[:3])
    disp = data.get("display_name")
    return disp[:120] if isinstance(disp, str) else None


async def cached_address(lat: float | None, lng: float | None) -> str | None:
    """Cache-only lookup — never touches the network. Safe for LIST endpoints."""
    if lat is None or lng is None:
        return None
    try:
        return await redis_client.get(cache_key(lat, lng))
    except Exception:
        return None


async def reverse_geocode(lat: float | None, lng: float | None) -> str | None:
    """Resolve one coordinate pair to a short address, cache-first.

    Returns None on any failure — an address is a nice-to-have on a screen, never
    a reason for a manager's page to error out.
    """
    if lat is None or lng is None:
        return None
    key = cache_key(lat, lng)
    try:
        hit = await redis_client.get(key)
        if hit:
            return hit
    except Exception:
        pass  # a cache outage must not stop the lookup

    global _last_call
    try:
        import httpx  # noqa: PLC0415 — keep the import out of the boot path

        async with _lock:  # serialise + honour the 1 req/s policy
            wait = MIN_INTERVAL_SECONDS - (time.monotonic() - _last_call)
            if wait > 0:
                await asyncio.sleep(wait)
            _last_call = time.monotonic()
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
                resp = await client.get(
                    NOMINATIM_URL,
                    params={
                        "lat": f"{lat:.4f}",
                        "lon": f"{lng:.4f}",
                        "format": "jsonv2",
                        "zoom": 14,  # village / suburb level, not house number
                        "addressdetails": 1,
                    },
                    headers={"User-Agent": USER_AGENT, "Accept-Language": "en"},
                )
        if resp.status_code != 200:
            logger.warning("reverse geocode HTTP %s for %.4f,%.4f", resp.status_code, lat, lng)
            return None
        address = _short_address(resp.json())
    except Exception as e:
        logger.warning("reverse geocode failed for %.4f,%.4f: %s", lat, lng, e)
        return None

    if address:
        try:
            await redis_client.set(key, address, ex=CACHE_TTL_SECONDS)
        except Exception:
            pass
    return address
