import logging
import uuid
from abc import ABC, abstractmethod

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Notification

logger = logging.getLogger("hogo.notify")


class PushSender(ABC):
    @abstractmethod
    async def push(self, expo_push_token: str | None, title: str, body: str) -> None: ...


class NoopPushSender(PushSender):
    """Actual Expo push delivery is wired in the mobile phase."""

    async def push(self, expo_push_token: str | None, title: str, body: str) -> None:
        logger.debug("Noop push: %s — %s", title, body)


class NotificationDispatcher:
    def __init__(self, push_sender: PushSender | None = None) -> None:
        self.push_sender = push_sender or NoopPushSender()

    async def notify(
        self,
        session: AsyncSession,
        recipient_id: uuid.UUID,
        type_: str,
        title: dict,
        body: dict,
        entity_type: str | None = None,
        entity_id: str | None = None,
    ) -> Notification:
        row = Notification(
            recipient_id=recipient_id,
            type=type_,
            title_en=title.get("en", ""),
            title_hi=title.get("hi", ""),
            title_mr=title.get("mr", ""),
            body_en=body.get("en", ""),
            body_hi=body.get("hi", ""),
            body_mr=body.get("mr", ""),
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id else None,
        )
        session.add(row)
        await self.push_sender.push(None, row.title_en, row.body_en)
        return row


dispatcher = NotificationDispatcher()

# Trilingual notification templates
T = {
    "incident_assigned": {
        "title": {"en": "New incident reported", "hi": "नई घटना दर्ज हुई", "mr": "नवीन घटना नोंदवली"},
    },
    "incident_status": {
        "title": {"en": "Incident status updated", "hi": "घटना की स्थिति बदली", "mr": "घटनेची स्थिती बदलली"},
    },
    "incident_escalated": {
        "title": {"en": "Incident escalated", "hi": "घटना एस्कलेट हुई", "mr": "घटना वरिष्ठांकडे पाठवली"},
    },
    "submission_pending": {
        "title": {"en": "Form submission awaiting approval", "hi": "फॉर्म अनुमोदन हेतु लंबित", "mr": "फॉर्म मंजुरीसाठी प्रलंबित"},
    },
    "submission_decided": {
        "title": {"en": "Your submission was reviewed", "hi": "आपके फॉर्म की समीक्षा हुई", "mr": "तुमच्या फॉर्मचे पुनरावलोकन झाले"},
    },
    "submission_escalated": {
        "title": {"en": "Form submission escalated", "hi": "फॉर्म एस्कलेट हुआ", "mr": "फॉर्म वरिष्ठांकडे पाठवला"},
    },
    "swap_request": {
        "title": {"en": "Shift swap request", "hi": "शिफ्ट अदला-बदली अनुरोध", "mr": "शिफ्ट अदलाबदल विनंती"},
    },
    "swap_manager_pending": {
        "title": {"en": "Shift swap needs your approval", "hi": "शिफ्ट अदला-बदली अनुमोदन हेतु", "mr": "शिफ्ट अदलाबदल मंजुरीसाठी"},
    },
    "swap_decided": {
        "title": {"en": "Shift swap decision", "hi": "शिफ्ट अदला-बदली निर्णय", "mr": "शिफ्ट अदलाबदल निर्णय"},
    },
    "registration_pending": {
        "title": {"en": "New worker registration", "hi": "नया कर्मचारी पंजीकरण", "mr": "नवीन कामगार नोंदणी"},
    },
    "registration_approved": {
        "title": {"en": "Your registration was approved", "hi": "आपका पंजीकरण स्वीकृत", "mr": "तुमची नोंदणी मंजूर झाली"},
    },
    "attendance_approved": {
        "title": {"en": "Flagged attendance approved", "hi": "चिह्नित उपस्थिति स्वीकृत", "mr": "चिन्हांकित हजेरी मंजूर"},
    },
}


def template(type_: str, body_text: str = "") -> tuple[dict, dict]:
    t = T.get(type_, {"title": {"en": type_, "hi": type_, "mr": type_}})
    body = {"en": body_text, "hi": body_text, "mr": body_text}
    return t["title"], body
