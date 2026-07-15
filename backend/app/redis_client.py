import redis.asyncio as aioredis

from app.config import settings

redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)


async def redis_write_probe() -> bool:
    """SET/GET/DEL probe at boot — a read-only Upstash token must fail LOUDLY."""
    import logging

    log = logging.getLogger("hogo.redis")
    try:
        await redis_client.set("boot:write_probe", "ok", ex=30)
        val = await redis_client.get("boot:write_probe")
        await redis_client.delete("boot:write_probe")
        if val != "ok":
            raise RuntimeError(f"probe read back {val!r}")
        log.info("Redis write probe OK (%s)", settings.redis_url.split("@")[-1])
        return True
    except Exception as e:
        log.critical(
            "REDIS WRITE PROBE FAILED — token may be READ-ONLY or URL wrong (%s): %s",
            settings.redis_url.split("@")[-1], e,
        )
        return False
