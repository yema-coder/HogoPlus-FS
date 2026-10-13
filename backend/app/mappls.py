"""Mappls (MapmyIndia) — server-side reverse geocoding + dashboard map token.

Design rules (owner mandate 2026-06):
  * Credentials (CLIENT_ID / CLIENT_SECRET) are read from env SERVER-SIDE ONLY. They are
    never sent to the mobile app, never logged, never committed.
  * Reverse geocoding (coords → readable Indian address) happens on the backend and is
    CACHED in the geocode_cache table (keyed on coords rounded to ~11 m) so we never pay
    for the same spot twice.
  * Everything fails GRACEFULLY: if Mappls is unreachable / out of quota / not configured,
    callers get None and the UI falls back to raw coordinates + "Open in Maps". The failure
    is logged, never surfaced to a user, and never blocks a punch or an incident.

Endpoints used (from the Mappls integration playbook):
  * OAuth token:     POST https://outpost.mappls.com/api/security/oauth/token
  * Reverse geocode: GET  https://search.mappls.com/search/address/rev-geocode
  * Still image:     GET  https://tile.mappls.com/map/raster_tile/still_image
"""
from __future__ import annotations

import asyncio
import logging
import time

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings

logger = logging.getLogger("hogo.mappls")

_TOKEN_URL = "https://outpost.mappls.com/api/security/oauth/token"
# This project authenticates REST calls with the OAuth token in the PATH
# (advancedmaps), not the Authorization header (search.mappls.com returns 401 for it).
_API_BASE = "https://apis.mappls.com/advancedmaps/v1"

_token_value: str | None = None
_token_expiry: float = 0.0
_token_lock = asyncio.Lock()


def mappls_configured() -> bool:
    return bool(settings.mappls_client_id and settings.mappls_client_secret)


async def get_token() -> str | None:
    """Cached OAuth bearer token (refreshed ~60 s early). None if unconfigured/unreachable."""
    global _token_value, _token_expiry
    if not mappls_configured():
        return None
    now = time.time()
    if _token_value and now < _token_expiry:
        return _token_value
    async with _token_lock:
        if _token_value and time.time() < _token_expiry:
            return _token_value
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                r = await client.post(
                    _TOKEN_URL,
                    data={
                        "grant_type": "client_credentials",
                        "client_id": settings.mappls_client_id,
                        "client_secret": settings.mappls_client_secret,
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
            if r.status_code != 200:
                logger.warning("Mappls token HTTP %s", r.status_code)
                return None
            j = r.json()
            tok = j.get("access_token")
            if not tok:
                logger.warning("Mappls token missing access_token")
                return None
            _token_value = tok
            _token_expiry = time.time() + max(0, int(j.get("expires_in", 3600)) - 60)
            return _token_value
        except Exception as e:
            logger.warning("Mappls token fetch failed: %s", e)
            return None


def _round_key(v: float) -> float:
    # ~11 m grid — field staff punch repeatedly in the same cell, so the cache hits hard.
    return round(float(v), 4)


def _format_address(x: dict) -> str | None:
    if not x:
        return None
    fa = (x.get("formatted_address") or "").strip()
    if fa:
        return fa[:300]
    parts: list[str] = []
    for k in ("poi", "street", "village", "subDistrict", "district", "state", "pincode"):
        v = (x.get(k) or "").strip() if isinstance(x.get(k), str) else ""
        if v and v not in parts:
            parts.append(v)
    line = ", ".join(parts[:5]).strip()
    return line[:300] or None


async def reverse_geocode(session: AsyncSession, lat: float, lng: float) -> str | None:
    """Coords → readable address, CACHED. None on any failure (caller falls back to coords)."""
    from app.models import GeocodeCache

    if lat is None or lng is None:
        return None
    lat_k, lng_k = _round_key(lat), _round_key(lng)
    cached = (
        await session.execute(
            select(GeocodeCache).where(
                GeocodeCache.lat_key == lat_k, GeocodeCache.lng_key == lng_k
            )
        )
    ).scalar_one_or_none()
    if cached is not None:
        return cached.address  # may be None (negative cache) — still avoids a repeat call

    token = await get_token()
    address: str | None = None
    if token:
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                r = await client.get(
                    f"{_API_BASE}/{token}/rev_geocode",
                    params={"lat": lat, "lng": lng},
                )
            if r.status_code == 200:
                results = (r.json() or {}).get("results") or []
                address = _format_address(results[0]) if results else None
            else:
                logger.warning("Mappls rev-geocode HTTP %s", r.status_code)
                return None  # transient — do NOT negative-cache a server error
        except Exception as e:
            logger.warning("Mappls rev-geocode failed: %s", e)
            return None
    else:
        return None

    # cache the result (including a confirmed "no address here" as empty) to avoid repeats
    try:
        session.add(GeocodeCache(lat_key=lat_k, lng_key=lng_k, address=address))
        await session.flush()
    except Exception:
        await session.rollback()
    return address


STATIC_CACHE_PREFIX = "mappls:static:"
STATIC_CACHE_TTL = 30 * 24 * 3600  # a map tile of a fixed spot does not change


def static_cache_key(lat: float, lng: float, zoom: int, size: str) -> str:
    """Same ~11 m grid as the geocode cache: managers reviewing the same punches
    (and three managers reviewing the SAME punch) must cost one Mappls call, not one
    per view per day. Zoom and size are part of the key — a different image is a
    different object."""
    return f"{STATIC_CACHE_PREFIX}{_round_key(lat)},{_round_key(lng)},z{int(zoom)},{size}"


async def static_map_png(lat: float, lng: float, zoom: int = 16, size: str = "400x260") -> bytes | None:
    """Still-image PNG for a mobile preview, proxied so the token never hits the client.
    Cached in Redis for 30 days on the ~11 m grid — without it every review of the
    same punch burned a fresh billed call. None on any failure → the app shows
    coords + Open-in-Maps instead.

    The bytes are base64-encoded in the cache because the shared Redis client runs
    with decode_responses=True; storing raw PNG bytes through it would corrupt them.
    """
    import base64  # noqa: PLC0415

    from app.redis_client import redis_client  # noqa: PLC0415

    key = static_cache_key(lat, lng, zoom, size)
    try:
        hit = await redis_client.get(key)
        if hit:
            return base64.b64decode(hit)
    except Exception:
        pass  # a cache outage must never stop the map from loading

    # ask Mappls for the ROUNDED point so the image matches the key it is stored under
    lat, lng = _round_key(lat), _round_key(lng)
    token = await get_token()
    if not token:
        return None
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(
                f"{_API_BASE}/{token}/still_image",
                params={
                    "center": f"{lat},{lng}", "zoom": zoom, "size": size, "ssf": 1,
                    "markers": f"{lat},{lng}",
                },
            )
        if r.status_code == 200 and r.headers.get("content-type", "").startswith("image"):
            try:
                await redis_client.set(key, base64.b64encode(r.content).decode(), ex=STATIC_CACHE_TTL)
            except Exception:
                pass
            return r.content
        logger.warning("Mappls still-image HTTP %s", r.status_code)
        return None
    except Exception as e:
        logger.warning("Mappls still-image failed: %s", e)
        return None
