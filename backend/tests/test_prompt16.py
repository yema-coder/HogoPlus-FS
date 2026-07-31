"""Prompt 16: app-version endpoint + Factory Pulse (fallback path)."""
import pytest

from tests.conftest import PHONES, login


async def test_app_version_empty_then_set(client, monkeypatch):
    r = await client.get("/api/app-version")
    assert r.status_code == 200

    cgm = await login(client, PHONES["cgm"])
    r = await client.put(
        "/api/admin/app-version",
        json={"latest_version": "1.0.7", "apk_url": "https://play.google.com/store/apps/details?id=com.hogoplus.fs", "notes": "polish"},
        headers=cgm,
    )
    assert r.status_code == 200, r.text
    r = await client.get("/api/app-version")
    assert r.json() == {
        "latest_version": "1.0.7",
        "apk_url": "https://play.google.com/store/apps/details?id=com.hogoplus.fs",
        "notes": "polish",
        "force_update": False,
    }
    # update overwrites the same single row
    r = await client.put("/api/admin/app-version", json={"latest_version": "1.0.8"}, headers=cgm)
    assert r.status_code == 200
    assert (await client.get("/api/app-version")).json()["latest_version"] == "1.0.8"


async def test_app_version_admin_guard(client):
    worker = await login(client, PHONES["w_prod1"])
    r = await client.put("/api/admin/app-version", json={"latest_version": "9.9.9"}, headers=worker)
    assert r.status_code == 403


async def test_app_version_rejects_placeholders_and_garbage(client):
    """2026-07-31: prod shipped latest_version seeded at 1.0.7 with a fake
    example.com apk_url — the update prompt never fired and the link was dead.
    The API must now refuse both failure modes."""
    cgm = await login(client, PHONES["cgm"])
    for bad in (
        {"latest_version": "abc"},                                            # not a version
        {"latest_version": "1.0.22", "apk_url": "http://insecure.host/x.apk"},  # not https
        {"latest_version": "1.0.22", "apk_url": "https://hogoplus.example.com/hogoplus-1.0.7.apk"},  # placeholder
    ):
        r = await client.put("/api/admin/app-version", json=bad, headers=cgm)
        assert r.status_code == 422, (bad, r.text)

    # empty apk_url normalises to NULL (no dead-end links), version echoes back
    r = await client.put(
        "/api/admin/app-version",
        json={"latest_version": "1.0.22", "apk_url": "  ", "notes": "six-feature build", "force_update": False},
        headers=cgm,
    )
    assert r.status_code == 200, r.text
    got = (await client.get("/api/app-version")).json()
    assert got["latest_version"] == "1.0.22"
    assert got["apk_url"] is None


async def test_factory_pulse_fallback_and_guard(client, monkeypatch):
    from app import ai_core

    async def boom(*a, **k):
        raise RuntimeError("no LLM in tests")

    monkeypatch.setattr(ai_core, "chat_answer", boom)
    cgm = await login(client, PHONES["cgm"])
    r = await client.get("/api/dashboard/pulse", headers=cgm)
    assert r.status_code == 200, r.text
    assert r.json()["pulse"]  # static fallback sentence
    # cached on second call
    r2 = await client.get("/api/dashboard/pulse", headers=cgm)
    assert r2.json()["cached"] is True

    worker = await login(client, PHONES["w_prod1"])
    assert (await client.get("/api/dashboard/pulse", headers=worker)).status_code == 403
