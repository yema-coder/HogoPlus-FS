import asyncio
import logging
import uuid
from abc import ABC, abstractmethod

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Employee, Notification

logger = logging.getLogger("hogo.notify")

# Wave-1 anti-spam: these types are BATCHED (max 1 push per recipient per type
# per 30 min) and respect quiet hours 22:00–06:00 IST — the inbox row is ALWAYS
# written; only the push wake-up is suppressed. Gated by
# settings.notif_batching_enabled (default OFF = today's behaviour).
BATCHED_TYPES = {"registration_pending", "submission_pending"}
BATCH_WINDOW_SECONDS = 30 * 60


async def _push_allowed(session: AsyncSession, recipient_id: uuid.UUID, type_: str) -> bool:
    if type_ not in BATCHED_TYPES:
        return True
    try:
        from sqlalchemy import select

        from app.models import FactorySettings

        s = (await session.execute(select(FactorySettings).limit(1))).scalar_one_or_none()
        if not s or not getattr(s, "notif_batching_enabled", False):
            return True
        from app.shift_logic import now_ist

        hour = now_ist().hour
        if hour >= 22 or hour < 6:
            return False  # quiet hours — inbox only
        from app.redis_client import redis_client

        key = f"push:batch:{recipient_id}:{type_}"
        # SET NX: first push in the window goes out; the rest roll up silently
        return bool(await redis_client.set(key, "1", nx=True, ex=BATCH_WINDOW_SECONDS))
    except Exception:
        return True  # anti-spam must never block a notification


class PushSender(ABC):
    @abstractmethod
    async def push(self, expo_push_token: str | None, title: str, body: str, data: dict | None = None) -> None: ...


class NoopPushSender(PushSender):
    """Used in tests; production uses ExpoPushSender."""

    async def push(self, expo_push_token: str | None, title: str, body: str, data: dict | None = None) -> None:
        logger.debug("Noop push: %s — %s", title, body)


class ExpoPushSender(PushSender):
    """Delivery via the Expo Push API, detached from the request path
    (asyncio.create_task) with 3 retry attempts + backoff. In-app notifications
    stay the source of truth — push is only the wake-up tap. Works in built
    APKs (Expo Go iOS has no push native module; tokens never register)."""

    async def push(self, expo_push_token: str | None, title: str, body: str, data: dict | None = None) -> None:
        if not expo_push_token or not expo_push_token.startswith("ExponentPushToken"):
            return
        asyncio.create_task(self._send_with_retry(expo_push_token, title, body, data))

    async def _send_with_retry(self, token: str, title: str, body: str, data: dict | None) -> None:
        import httpx

        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=8) as client:
                    res = await client.post(
                        "https://exp.host/--/api/v2/push/send",
                        json={
                            "to": token,
                            "title": title,
                            "body": body,
                            "data": data or {},
                            "sound": "default",
                        },
                    )
                    if res.status_code < 500:
                        return
            except Exception:
                pass
            await asyncio.sleep(2 ** attempt)
        logger.warning("expo push failed after 3 attempts (non-blocking)")


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
        # demo bubble: a notification's class always matches its recipient's class
        # (fanout never crosses the boundary — session.get hits the identity map)
        recipient = await session.get(Employee, recipient_id)
        row = Notification(
            is_demo=bool(recipient.is_demo) if recipient else False,
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
        # push mirrors the in-app notification, in the recipient's language
        lang = (recipient.language_pref if recipient else "mr") or "mr"
        await self.push_sender.push(
            recipient.expo_push_token if recipient else None,
            title.get(lang, row.title_en) or row.title_en,
            body.get(lang, row.body_en) or row.body_en,
            {"type": type_, "entity_type": entity_type, "entity_id": row.entity_id},
        )
        return row


import os as _os  # noqa: E402

dispatcher = NotificationDispatcher(
    NoopPushSender() if _os.environ.get("TESTING") else ExpoPushSender()
)

# Trilingual notification templates
T = {
    "welcome": {
        "title": {
            "en": "Welcome to HogoPlus! 🎉",
            "hi": "HogoPlus में आपका स्वागत है! 🎉",
            "mr": "HogoPlus मध्ये स्वागत आहे! 🎉",
        },
    },
    "announcement": {
        "title": {"en": "📢 Announcement", "hi": "📢 सूचना", "mr": "📢 सूचना"},
    },
    "incident_reassigned": {
        "title": {
            "en": "Incident assigned to you",
            "hi": "घटना आपको सौंपी गई",
            "mr": "घटना तुमच्याकडे सोपवली",
        },
    },
    "incident_forwarded": {
        "title": {
            "en": "Your complaint was forwarded",
            "hi": "आपकी शिकायत आगे भेजी गई",
            "mr": "तुमची तक्रार पुढे पाठवली",
        },
    },
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
    "attendance_face_mismatch": {
        "title": {"en": "Face mismatch on punch-in", "hi": "पंच-इन पर चेहरा मेल नहीं खाया", "mr": "पंच-इनला चेहरा जुळला नाही"},
    },
    "incident_critical": {
        "title": {"en": "CRITICAL incident detected", "hi": "गंभीर घटना का पता चला", "mr": "गंभीर घटना आढळली"},
    },
    "report_ready": {
        "title": {"en": "Daily factory report is ready", "hi": "दैनिक कारखाना रिपोर्ट तैयार", "mr": "दैनिक कारखाना अहवाल तयार"},
    },
    "face_enrolled": {
        "title": {
            "en": "New face reference enrolled",
            "hi": "नया चेहरा संदर्भ दर्ज हुआ",
            "mr": "नवीन चेहरा संदर्भ नोंदवला",
        },
    },
    "punchout_reminder": {
        "title": {"en": "Forgot to punch out?", "hi": "पंच आउट करना भूल गए?", "mr": "पंच आउट करायला विसरलात?"},
        "body": {
            "en": "Your shift ended — please punch out now.",
            "hi": "आपकी शिफ्ट खत्म हो गई — कृपया अभी पंच आउट करें।",
            "mr": "तुमची शिफ्ट संपली — कृपया आत्ता पंच आउट करा.",
        },
    },
    "vehicle_overstay": {
        "title": {
            "en": "🚚 Vehicle inside for over 12 hours",
            "hi": "🚚 वाहन 12 घंटे से अंदर है",
            "mr": "🚚 वाहन १२ तासांहून जास्त आत आहे",
        },
    },
    "regularization_requested": {
        "title": {
            "en": "Attendance dispute raised",
            "hi": "उपस्थिति पर आपत्ति दर्ज हुई",
            "mr": "हजेरीवर आक्षेप नोंदवला",
        },
    },
    "regularization_decided": {
        "title": {
            "en": "Your attendance request was reviewed",
            "hi": "आपके उपस्थिति अनुरोध की समीक्षा हुई",
            "mr": "तुमच्या हजेरी विनंतीचे पुनरावलोकन झाले",
        },
    },
}


def template(type_: str, body_text: str = "") -> tuple[dict, dict]:
    t = T.get(type_, {"title": {"en": type_, "hi": type_, "mr": type_}})
    if not body_text and "body" in t:
        return t["title"], t["body"]
    body = {"en": body_text, "hi": body_text, "mr": body_text}
    return t["title"], body
