import logging
from abc import ABC, abstractmethod

import httpx

from app.config import settings

logger = logging.getLogger("hogo.otp")

SMSGATEWAYHUB_URL = "https://www.smsgatewayhub.com/api/mt/SendSMS"
OTP_TTL_MINUTES = "5"  # must match OTP_TTL_SECONDS in auth.py (300s)


class NotConfigured(Exception):
    pass


class SMSDeliveryError(Exception):
    """Provider accepted the HTTP call but reported a delivery/validation error."""


class OTPSender(ABC):
    @abstractmethod
    async def send(self, phone: str, otp: str) -> None: ...


class DemoSender(OTPSender):
    """Logs the OTP. DEMO_OTP is also accepted at verify time when DEMO_OTP_ENABLED."""

    async def send(self, phone: str, otp: str) -> None:
        logger.info("[DEMO OTP] phone=%s otp=%s (demo code %s also accepted)", phone, otp, settings.demo_otp)


class MSG91Sender(OTPSender):
    """Stub: real MSG91 wiring arrives when MSG91_AUTH_KEY is provided."""

    def __init__(self) -> None:
        if not settings.msg91_auth_key or not settings.msg91_otp_template_id:
            raise NotConfigured("MSG91_AUTH_KEY / MSG91_OTP_TEMPLATE_ID not configured")

    async def send(self, phone: str, otp: str) -> None:
        # Placeholder for httpx call to MSG91 OTP API using
        # settings.msg91_auth_key and settings.msg91_otp_template_id.
        raise NotConfigured("MSG91 delivery not yet wired — set OTP_MODE=demo")


class WhatsAppSender(OTPSender):
    """Stub for a future WhatsApp delivery channel."""

    def __init__(self) -> None:
        raise NotConfigured("WhatsApp OTP delivery not yet configured")

    async def send(self, phone: str, otp: str) -> None:
        raise NotConfigured("WhatsApp OTP delivery not yet configured")


class SMSGatewayHubSender(OTPSender):
    """SMSGatewayHub SendSMS HTTP API — transactional route (channel=2) with the
    DLT sender ID + template ID attached so DLT scrubbing passes.

    The message text is the EXACT approved DLT template with ONLY the {#var#}
    placeholders substituted (1st = OTP, 2nd = validity minutes). Changing any
    other word makes DLT scrubbing silently drop the SMS.
    """

    def __init__(self) -> None:
        if not (
            settings.smsgatewayhub_api_key
            and settings.smsgatewayhub_sender_id
            and settings.smsgatewayhub_dlt_template_id
            and settings.otp_template_text
        ):
            raise NotConfigured(
                "SMSGATEWAYHUB_API_KEY / SMSGATEWAYHUB_SENDER_ID / "
                "SMSGATEWAYHUB_DLT_TEMPLATE_ID / OTP_TEMPLATE_TEXT not configured"
            )

    @staticmethod
    def build_message(otp: str) -> str:
        return (
            settings.otp_template_text
            .replace("{#var#}", otp, 1)
            .replace("{#var#}", OTP_TTL_MINUTES, 1)
        )

    @classmethod
    def build_params(cls, phone: str, otp: str) -> dict:
        params = {
            "APIKey": settings.smsgatewayhub_api_key,
            "senderid": settings.smsgatewayhub_sender_id,
            "channel": "2",  # transactional route
            "DCS": "0",  # plain GSM text
            "flashsms": "0",
            "number": phone.lstrip("+"),  # international format without '+'
            "text": cls.build_message(otp),
            "route": "1",
            "dlttemplateid": settings.smsgatewayhub_dlt_template_id,
        }
        if settings.smsgatewayhub_entity_id:
            params["EntityId"] = settings.smsgatewayhub_entity_id
        return params

    async def send_raw(self, phone: str, otp: str) -> dict:
        """Call the provider and return its raw response JSON. Raises on any failure."""
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(SMSGATEWAYHUB_URL, params=self.build_params(phone, otp))
            resp.raise_for_status()
            data = resp.json()
        if str(data.get("ErrorCode")) not in ("0", "000"):
            raise SMSDeliveryError(
                f"SMSGatewayHub error {data.get('ErrorCode')}: {data.get('ErrorMessage')}"
            )
        return data

    async def send(self, phone: str, otp: str) -> None:
        try:
            data = await self.send_raw(phone, otp)
            logger.info("SMSGatewayHub OTP queued phone=%s job=%s", phone, data.get("JobId"))
        except Exception as e:
            logger.error("SMSGatewayHub send failed for %s: %s", phone, e)
            if settings.demo_otp_enabled:
                # non-prod: never brick login — fall back to demo behavior
                logger.info(
                    "[FALLBACK DEMO OTP] phone=%s otp=%s (demo code %s also accepted)",
                    phone, otp, settings.demo_otp,
                )
            else:
                raise SMSDeliveryError(str(e)) from e


def get_otp_sender() -> OTPSender:
    mode = settings.otp_mode.lower()
    if mode == "demo":
        return DemoSender()
    if mode == "msg91":
        return MSG91Sender()
    if mode == "smsgatewayhub":
        return SMSGatewayHubSender()
    if mode == "whatsapp":
        return WhatsAppSender()
    raise NotConfigured(f"Unknown OTP_MODE '{settings.otp_mode}'")
