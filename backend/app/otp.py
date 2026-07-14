import logging
from abc import ABC, abstractmethod

from app.config import settings

logger = logging.getLogger("hogo.otp")


class NotConfigured(Exception):
    pass


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


def get_otp_sender() -> OTPSender:
    mode = settings.otp_mode.lower()
    if mode == "demo":
        return DemoSender()
    if mode == "msg91":
        return MSG91Sender()
    if mode == "whatsapp":
        return WhatsAppSender()
    raise NotConfigured(f"Unknown OTP_MODE '{settings.otp_mode}'")
