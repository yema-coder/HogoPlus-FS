import logging
from abc import ABC, abstractmethod

import httpx

from app.config import settings

logger = logging.getLogger("hogo.otp")

SMSGATEWAYHUB_URL = "https://www.smsgatewayhub.com/api/mt/SendSMS"
OTP_TTL_MINUTES = "5"  # must match OTP_TTL_SECONDS in auth.py (300s)


def mask_phone(phone: str) -> str:
    """+918483029039 → +91848****39 — production logs never carry a full number."""
    if len(phone) <= 7:
        return "***"
    return f"{phone[:6]}{'*' * (len(phone) - 8)}{phone[-2:]}"


def mask_key(key: str) -> str:
    return f"{key[:4]}****" if key else "(unset)"



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
        if settings.demo_otp_enabled:
            logger.info("[DEMO OTP] phone=%s otp=%s (demo code %s also accepted)", phone, otp, settings.demo_otp)
        else:
            logger.info("[DEMO OTP] phone=%s otp=%s (DEMO_OTP_ENABLED=false — fixed demo code NOT accepted)", phone, otp)


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
        """Call the provider and return its raw response JSON.

        Prompt 21 Bug-1 logging contract: per attempt, log the RAW HTTP status +
        response body + message id with the API key masked. NEVER log the OTP value
        here. NO exception is swallowed — every failure raises SMSDeliveryError.
        """
        params = self.build_params(phone, otp)
        logger.info(
            "SMSGatewayHub SEND phone=%s sender=%s dlt_template=%s entity_id=%s api_key=%s",
            mask_phone(phone), params.get("senderid"), params.get("dlttemplateid"),
            params.get("EntityId", "(not sent)"), mask_key(settings.smsgatewayhub_api_key),
        )
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(SMSGATEWAYHUB_URL, params=params)
        body_text = resp.text
        logger.info(
            "SMSGatewayHub RESPONSE phone=%s http_status=%s body=%s",
            mask_phone(phone), resp.status_code, body_text[:500],
        )
        if resp.status_code != 200:
            raise SMSDeliveryError(f"SMSGatewayHub HTTP {resp.status_code}: {body_text[:300]}")
        try:
            data = resp.json()
        except ValueError:
            raise SMSDeliveryError(f"SMSGatewayHub non-JSON response: {body_text[:300]}")
        if str(data.get("ErrorCode")) not in ("0", "000"):
            raise SMSDeliveryError(
                f"SMSGatewayHub error {data.get('ErrorCode')}: {data.get('ErrorMessage')}"
            )
        return data

    async def send(self, phone: str, otp: str) -> None:
        # NO silent demo fallback (Bug 1 fix): any gateway failure surfaces to the
        # caller as SMSDeliveryError → HTTP 502. Demo delivery now requires an
        # explicit OTP_MODE=demo.
        try:
            data = await self.send_raw(phone, otp)
        except SMSDeliveryError:
            raise
        except Exception as e:
            logger.error(
                "SMSGatewayHub send FAILED phone=%s error=%s: %s",
                mask_phone(phone), type(e).__name__, e,
            )
            raise SMSDeliveryError(f"{type(e).__name__}: {e}") from e
        message_id = None
        message_data = data.get("MessageData")
        if isinstance(message_data, list) and message_data:
            message_id = message_data[0].get("MessageId")
        logger.info(
            "SMSGatewayHub OTP queued phone=%s job_id=%s message_id=%s",
            mask_phone(phone), data.get("JobId"), message_id,
        )


def get_otp_sender() -> OTPSender:
    mode = settings.otp_mode.strip().lower()
    if not mode:
        raise NotConfigured(
            "OTP_MODE_NOT_SET: OTP_MODE is empty — the container did not receive "
            ".env values. Set OTP_MODE=demo|smsgatewayhub|msg91|whatsapp."
        )
    if mode == "demo":
        return DemoSender()
    if mode == "msg91":
        return MSG91Sender()
    if mode == "smsgatewayhub":
        return SMSGatewayHubSender()
    if mode == "whatsapp":
        return WhatsAppSender()
    raise NotConfigured(f"Unknown OTP_MODE '{settings.otp_mode}'")
