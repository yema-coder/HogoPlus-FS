"""Prompt 19 launch-eve hardening regressions.

Guards a worker-triggerable 500: filtering incident/form lists by an invalid
enum status previously hit Postgres (invalid input value for enum ...) and
returned 500. It must now return 422.
"""
from tests.conftest import PHONES, login


async def test_incidents_invalid_status_filter_returns_422(client):
    headers = await login(client, PHONES["cgm"])
    r = await client.get("/api/incidents?status=' OR '1'='1", headers=headers)
    assert r.status_code == 422, r.text


async def test_incidents_valid_status_filter_ok(client):
    headers = await login(client, PHONES["cgm"])
    r = await client.get("/api/incidents?status=submitted", headers=headers)
    assert r.status_code == 200, r.text


async def test_form_submissions_invalid_status_filter_returns_422(client):
    headers = await login(client, PHONES["cgm"])
    r = await client.get("/api/submissions?status=bogus", headers=headers)
    assert r.status_code == 422, r.text
