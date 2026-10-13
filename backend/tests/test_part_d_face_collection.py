"""Part D — attendance face REFERENCE collection (data only, flag OFF by default).

Covers the GUARDRAILS (the data-pipeline itself needs the vision models + a real
selfie and is verified out-of-band): the master flag defaults OFF, is reflected in
the admin settings payload, can be toggled by CGM, and the background collector is
a strict no-op while the flag is OFF.
"""
from sqlalchemy import select, text

from app.models import FactorySettings
from app.tasks import run_face_collection_background
from tests.conftest import PHONES, login


async def test_face_collection_flag_defaults_off_and_toggles(client, db_session):
    cgm = await login(client, PHONES["cgm"])

    r = await client.get("/api/admin/settings", headers=cgm)
    assert r.status_code == 200
    assert r.json()["face_collection_enabled"] is False  # ships OFF

    r = await client.patch(
        "/api/admin/settings", json={"face_collection_enabled": True}, headers=cgm
    )
    assert r.status_code == 200
    assert r.json()["face_collection_enabled"] is True

    # restore default OFF
    r = await client.patch(
        "/api/admin/settings", json={"face_collection_enabled": False}, headers=cgm
    )
    assert r.json()["face_collection_enabled"] is False


async def test_face_collection_is_noop_when_flag_off(db_session):
    s = (await db_session.execute(select(FactorySettings).limit(1))).scalar_one()
    s.face_collection_enabled = False
    await db_session.commit()

    before = (await db_session.execute(text("SELECT COUNT(*) FROM face_references"))).scalar()
    # a bogus attendance id must never raise and must store nothing
    await run_face_collection_background("00000000-0000-0000-0000-000000000000")
    after = (await db_session.execute(text("SELECT COUNT(*) FROM face_references"))).scalar()
    assert after == before == 0
