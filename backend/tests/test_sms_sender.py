"""SMSGatewayHub OTP sender — mocked provider tests.

Covers: exact DLT template substitution, SendSMS payload shape, ErrorCode handling,
no-silent-fallback on provider failure (Prompt 21 Bug-1), get_otp_sender mode,
and the CGM-only POST /api/admin/test-sms endpoint.
"""
import pytest

from app import otp as otp_mod
from app.config import settings
from app.otp import (
    NotConfigured,
    SMSDeliveryError,
    SMSGatewayHubSender,
    get_otp_sender,
)
from tests.conftest import PHONES, login

TEMPLATE = (
    "Dear User, your OTP for verification of V2S is {#var#}. "
    "OTP valid for {#var#} min. Do not share this with anyone."
)


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    @property
    def text(self):
        import json as _json

        return _json.dumps(self._payload)

    def json(self):
        return self._payload


class FakeAsyncClient:
    """Stands in for httpx.AsyncClient; records the GET params."""

    captured: dict = {}
    payload: dict = {"ErrorCode": "000", "ErrorMessage": "Success", "JobId": "20047"}
    exc: Exception | None = None

    def __init__(self, *a, **kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, params=None):
        if FakeAsyncClient.exc:
            raise FakeAsyncClient.exc
        FakeAsyncClient.captured = {"url": url, "params": params}
        return FakeResponse(FakeAsyncClient.payload)


@pytest.fixture(autouse=True)
def sms_settings(monkeypatch):
    monkeypatch.setattr(settings, "smsgatewayhub_api_key", "test-api-key")
    monkeypatch.setattr(settings, "smsgatewayhub_sender_id", "VTSFSM")
    monkeypatch.setattr(settings, "smsgatewayhub_dlt_template_id", "1107175861589542403")
    monkeypatch.setattr(settings, "otp_template_text", TEMPLATE)
    monkeypatch.setattr(otp_mod.httpx, "AsyncClient", FakeAsyncClient)
    FakeAsyncClient.captured = {}
    FakeAsyncClient.payload = {"ErrorCode": "000", "ErrorMessage": "Success", "JobId": "20047"}
    FakeAsyncClient.exc = None
    yield


def test_exact_template_substitution():
    """1st {#var#} = OTP, 2nd {#var#} = '5'; every other word untouched (DLT scrubbing)."""
    msg = SMSGatewayHubSender.build_message("482913")
    assert msg == (
        "Dear User, your OTP for verification of V2S is 482913. "
        "OTP valid for 5 min. Do not share this with anyone."
    )
    assert "{#var#}" not in msg


async def test_sendsms_payload_shape():
    sender = SMSGatewayHubSender()
    await sender.send_raw("+919876543210", "123456")
    assert FakeAsyncClient.captured["url"] == otp_mod.SMSGATEWAYHUB_URL
    p = FakeAsyncClient.captured["params"]
    assert p["APIKey"] == "test-api-key"
    assert p["senderid"] == "VTSFSM"
    assert p["channel"] == "2"  # transactional route
    assert p["DCS"] == "0" and p["flashsms"] == "0" and p["route"] == "1"
    assert p["number"] == "919876543210"  # no leading '+'
    assert p["dlttemplateid"] == "1107175861589542403"
    assert "EntityId" not in p  # not configured -> not attached
    assert p["text"] == SMSGatewayHubSender.build_message("123456")


async def test_provider_error_code_raises():
    FakeAsyncClient.payload = {"ErrorCode": "007", "ErrorMessage": "Invalid Sender"}
    with pytest.raises(SMSDeliveryError):
        await SMSGatewayHubSender().send_raw("+919876543210", "123456")


async def test_send_raises_even_with_demo_enabled(monkeypatch):
    """Prompt 21 Bug-1: the silent demo fallback was REMOVED — gateway failures always
    surface as SMSDeliveryError regardless of DEMO_OTP_ENABLED."""
    FakeAsyncClient.exc = RuntimeError("network down")
    monkeypatch.setattr(settings, "demo_otp_enabled", True)
    with pytest.raises(SMSDeliveryError):
        await SMSGatewayHubSender().send("+919876543210", "123456")


async def test_send_raises_in_prod(monkeypatch):
    FakeAsyncClient.exc = RuntimeError("network down")
    monkeypatch.setattr(settings, "demo_otp_enabled", False)
    with pytest.raises(SMSDeliveryError):
        await SMSGatewayHubSender().send("+919876543210", "123456")


def test_get_otp_sender_mode_and_not_configured(monkeypatch):
    monkeypatch.setattr(settings, "otp_mode", "smsgatewayhub")
    assert isinstance(get_otp_sender(), SMSGatewayHubSender)
    monkeypatch.setattr(settings, "otp_template_text", "")
    with pytest.raises(NotConfigured):
        get_otp_sender()


async def test_admin_test_sms_endpoint(client):
    cgm = await login(client, PHONES["cgm"])
    r = await client.post("/api/admin/test-sms", json={"phone": "+919876543210"}, headers=cgm)
    assert r.status_code == 200
    body = r.json()
    assert body["sent"] is True
    assert body["provider_response"]["ErrorCode"] == "000"
    assert body["provider_response"]["JobId"] == "20047"
    # provider error surfaces as 502 with raw detail
    FakeAsyncClient.payload = {"ErrorCode": "007", "ErrorMessage": "Invalid Sender"}
    r = await client.post("/api/admin/test-sms", json={"phone": "+919876543210"}, headers=cgm)
    assert r.status_code == 502 and "007" in r.json()["detail"]
    # Manager (rank 3) forbidden
    mgr = await login(client, PHONES["prod_mgr"])
    r = await client.post("/api/admin/test-sms", json={"phone": "+919876543210"}, headers=mgr)
    assert r.status_code == 403
