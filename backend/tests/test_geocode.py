"""Reverse-geocode helper: cache key, address shortening, failure behaviour.

Pure logic — no network, no database. The live Nominatim call is exercised only
through a stubbed client so the suite never depends on an external service.
"""
import asyncio
import types

from app import geocode


def test_cache_key_rounds_to_about_eleven_metres():
    # 4 decimals: two punches from the same yard share one cache entry (one lookup)
    assert geocode.cache_key(19.3134831, 74.7093842) == "geo:rev:19.3135,74.7094"
    assert geocode.cache_key(19.31348, 74.70938) == geocode.cache_key(19.31349, 74.70939)
    # but a different village does not collide
    assert geocode.cache_key(19.3135, 74.7094) != geocode.cache_key(19.4135, 74.7094)


def test_short_address_prefers_nearest_first_and_drops_duplicates():
    data = {"address": {"village": "Kolhar", "state_district": "Ahmednagar",
                        "state": "Maharashtra", "country": "India"}}
    assert geocode._short_address(data) == "Kolhar, Ahmednagar, Maharashtra"
    # duplicated names collapse instead of repeating
    dup = {"address": {"town": "Shrirampur", "city": "Shrirampur", "state": "Maharashtra"}}
    assert geocode._short_address(dup) == "Shrirampur, Maharashtra"


def test_short_address_falls_back_to_display_name_then_none():
    assert geocode._short_address({"display_name": "x" * 300}).startswith("x")
    assert len(geocode._short_address({"display_name": "x" * 300})) == 120
    assert geocode._short_address({}) is None


def test_missing_coordinates_never_call_out():
    assert asyncio.run(geocode.reverse_geocode(None, 74.7)) is None
    assert asyncio.run(geocode.reverse_geocode(19.3, None)) is None
    assert asyncio.run(geocode.cached_address(None, None)) is None


def test_cache_hit_short_circuits_the_network(monkeypatch):
    async def fake_get(key):
        return "Kolhar, Ahmednagar, Maharashtra"
    monkeypatch.setattr(geocode.redis_client, "get", fake_get)
    called = {"n": 0}

    def boom(*a, **k):
        called["n"] += 1
        raise AssertionError("network must not be touched on a cache hit")
    monkeypatch.setitem(__import__("sys").modules, "httpx", types.SimpleNamespace(AsyncClient=boom))
    assert asyncio.run(geocode.reverse_geocode(19.3135, 74.7094)) == "Kolhar, Ahmednagar, Maharashtra"
    assert called["n"] == 0


def test_a_failing_lookup_returns_none_rather_than_raising(monkeypatch):
    async def miss(key):
        return None
    monkeypatch.setattr(geocode.redis_client, "get", miss)

    class Boom:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): raise RuntimeError("nominatim down")
        async def __aexit__(self, *a): return False
    monkeypatch.setitem(__import__("sys").modules, "httpx", types.SimpleNamespace(AsyncClient=Boom))
    assert asyncio.run(geocode.reverse_geocode(19.3135, 74.7094)) is None
