"""The static-map proxy must cost ONE Mappls call per spot, not one per view.

Pure: a stub Redis and a stub httpx, no network, no database.
"""
import asyncio
import base64
import sys
import types

from app import mappls


class FakeRedis:
    def __init__(self):
        self.store = {}
        self.gets = 0
    async def get(self, k):
        self.gets += 1
        return self.store.get(k)
    async def set(self, k, v, ex=None):
        self.store[k] = v


def _install(monkey_redis, png=b"\x89PNG-fake-bytes", status=200, ctype="image/png", calls=None):
    """Point app.redis_client.redis_client at the fake and stub the httpx that
    mappls.py bound at import time (patching sys.modules would be too late)."""
    import app.redis_client as rc
    rc.redis_client = monkey_redis

    class Resp:
        status_code = status
        headers = {"content-type": ctype}
        content = png
    class Client:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, *a, **k):
            if calls is not None:
                calls.append(1)
            return Resp()
    mappls.httpx = types.SimpleNamespace(AsyncClient=Client)


def test_cache_key_uses_the_same_11m_grid_and_includes_zoom_and_size():
    a = mappls.static_cache_key(19.3134831, 74.7093842, 16, "400x260")
    b = mappls.static_cache_key(19.31348, 74.70938, 16, "400x260")
    assert a == b, "two punches from the same yard must share one cached image"
    assert a != mappls.static_cache_key(19.3135, 74.7094, 17, "400x260")
    assert a != mappls.static_cache_key(19.3135, 74.7094, 16, "800x600")
    assert a.startswith("mappls:static:")


def test_second_view_of_the_same_spot_costs_no_mappls_call():
    calls = []
    r = FakeRedis()
    _install(r, calls=calls)
    mappls.get_token = lambda: _done("tok")
    first = asyncio.run(mappls.static_map_png(19.3135, 74.7094))
    second = asyncio.run(mappls.static_map_png(19.3135, 74.7094))
    third = asyncio.run(mappls.static_map_png(19.31351, 74.70941))  # same 11 m cell
    assert first == second == third == b"\x89PNG-fake-bytes"
    assert len(calls) == 1, f"expected 1 billed call, got {len(calls)}"


def test_a_cache_outage_still_serves_the_map():
    class Broken(FakeRedis):
        async def get(self, k): raise RuntimeError("redis down")
        async def set(self, k, v, ex=None): raise RuntimeError("redis down")
    calls = []
    _install(Broken(), calls=calls)
    mappls.get_token = lambda: _done("tok")
    assert asyncio.run(mappls.static_map_png(19.3135, 74.7094)) == b"\x89PNG-fake-bytes"
    assert len(calls) == 1


def test_a_failed_fetch_is_not_cached():
    r = FakeRedis()
    calls = []
    _install(r, status=503, ctype="text/plain", calls=calls)
    mappls.get_token = lambda: _done("tok")
    assert asyncio.run(mappls.static_map_png(19.3135, 74.7094)) is None
    assert r.store == {}, "a failure must never poison the cache"


def test_stored_value_is_base64_so_decode_responses_cannot_corrupt_it():
    r = FakeRedis()
    _install(r)
    mappls.get_token = lambda: _done("tok")
    asyncio.run(mappls.static_map_png(19.3135, 74.7094))
    stored = next(iter(r.store.values()))
    assert isinstance(stored, str)
    assert base64.b64decode(stored) == b"\x89PNG-fake-bytes"


async def _done(v):
    return v
