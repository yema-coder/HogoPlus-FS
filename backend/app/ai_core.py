"""Universal-Key AI helpers: vision extraction, text LLM (JSON), Whisper STT,
plus Redis result-cache and daily usage counters.

Cost discipline: identical calls cached 24h by (endpoint, photo_key); every call
increments ai:usage:{YYYY-MM-DD}:{kind}.
"""
import base64
import json
import logging
import re
import tempfile
import uuid
from pathlib import Path

from app.config import settings
from app.redis_client import redis_client
from app.shift_logic import now_ist

logger = logging.getLogger("hogo.ai")

GEMINI_MODEL = "gemini-2.5-flash"


def llm_route() -> tuple[str, str, str]:
    """(api_key, provider, model) for ALL text/vision/chat LLM calls.

    Production: the factory's own OpenAI account (OPENAI_API_KEY) — dedicated
    billing and per-feature cost visibility, fully isolated from the Emergent
    universal key. Fallback (sandbox/dev only): Emergent key + Gemini."""
    if settings.openai_api_key:
        return settings.openai_api_key, "openai", settings.openai_model
    return settings.emergent_llm_key, "gemini", GEMINI_MODEL


def speech_key() -> str:
    """Whisper STT + TTS key: the factory's OpenAI account first, Emergent fallback."""
    return settings.openai_api_key or settings.emergent_llm_key


def active_model() -> str:
    return llm_route()[2]


class AiError(Exception):
    pass


def _parse_json(raw: str) -> dict:
    """LLM responses sometimes wrap JSON in ``` fences — strip and parse."""
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
    raise AiError(f"Model did not return valid JSON: {raw[:200]}")


async def vision_json(prompt: str, image_bytes: bytes) -> dict:
    """Temperature-0 vision extraction returning parsed JSON."""
    from emergentintegrations.llm.chat import ImageContent, LlmChat, UserMessage

    api_key, provider, model = llm_route()
    chat = (
        LlmChat(
            api_key=api_key,
            session_id=f"vision-{uuid.uuid4().hex[:12]}",
            system_message="You are a precise visual extraction engine. Respond ONLY with valid JSON, no prose.",
        )
        .with_model(provider, model)
        .with_params(temperature=0)
    )
    msg = UserMessage(
        text=prompt,
        file_contents=[ImageContent(base64.b64encode(image_bytes).decode())],
    )
    raw = await chat.send_message(msg)
    return _parse_json(raw)


async def text_json(system: str, prompt: str) -> dict:
    """Temperature-0 text task returning parsed JSON."""
    from emergentintegrations.llm.chat import LlmChat, UserMessage

    api_key, provider, model = llm_route()
    chat = (
        LlmChat(
            api_key=api_key,
            session_id=f"text-{uuid.uuid4().hex[:12]}",
            system_message=system,
        )
        .with_model(provider, model)
        .with_params(temperature=0)
    )
    raw = await chat.send_message(UserMessage(text=prompt))
    return _parse_json(raw)


async def chat_answer(system: str, prompt: str) -> str:
    """Grounded RAG answer — plain text."""
    from emergentintegrations.llm.chat import LlmChat, UserMessage

    api_key, provider, model = llm_route()
    chat = (
        LlmChat(
            api_key=api_key,
            session_id=f"chat-{uuid.uuid4().hex[:12]}",
            system_message=system,
        )
        .with_model(provider, model)
        .with_params(temperature=0.2)
    )
    return (await chat.send_message(UserMessage(text=prompt))).strip()


WHISPER_LANG_MAP = {"marathi": "mr", "hindi": "hi", "english": "en"}


async def transcribe_audio(audio_bytes: bytes, ext: str) -> tuple[str, str]:
    """Whisper STT with auto language detection → (transcript, lang_code mr/hi/en)."""
    from emergentintegrations.llm.openai.speech_to_text import OpenAISpeechToText

    stt = OpenAISpeechToText(api_key=speech_key())
    suffix = f".{ext}" if not ext.startswith(".") else ext
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(audio_bytes)
        tmp_path = tmp.name
    try:
        with open(tmp_path, "rb") as f:
            resp = await stt.transcribe(
                f,
                model="whisper-1",
                response_format="verbose_json",
                # Devanagari-context prompt: biases Whisper toward mr/hi in Devanagari
                # script instead of Urdu/Arabic script for Indian factory speech.
                prompt="मराठी किंवा हिंदी: स्टेशन, ब्रिक्स, वजन, शिफ्ट, मशीन, शेरा, फॉर्म भरा.",
            )
    finally:
        Path(tmp_path).unlink(missing_ok=True)
    transcript = getattr(resp, "text", "") or ""
    language_raw = (getattr(resp, "language", "") or "").lower()
    lang = WHISPER_LANG_MAP.get(language_raw, language_raw[:2] if language_raw else "hi")
    if lang not in ("mr", "hi", "en"):
        lang = "hi"
    return transcript, lang


# ---------------- Voice-first + Read-aloud (v1.0.21) ----------------

TTS_MODEL, TTS_VOICE = "tts-1", "alloy"


async def synthesize_speech(text: str) -> bytes:
    """OpenAI TTS via Universal Key → mp3 bytes (voices are multilingual —
    Marathi/Hindi Devanagari text is spoken natively)."""
    from emergentintegrations.llm.openai.text_to_speech import OpenAITextToSpeech

    tts = OpenAITextToSpeech(api_key=speech_key())
    return await tts.generate_speech(
        text=text, model=TTS_MODEL, voice=TTS_VOICE, response_format="mp3"
    )


async def describe_from_transcript(transcript: str, lang: str) -> str:
    """LLM rewrites a spoken factory report into a short WRITTEN incident
    description in the SPEAKER'S language. Never fails — falls back to the
    raw transcript so a voice report is never lost."""
    lang_name = {"mr": "Marathi", "hi": "Hindi", "en": "English"}.get(lang, "Marathi")
    try:
        result = await text_json(
            "You turn spoken factory-floor incident reports into short written "
            "descriptions. Respond ONLY with valid JSON.",
            f'Spoken report ({lang_name}): "{transcript}"\n\n'
            f"Write a clear 1-3 sentence incident description in {lang_name}, keeping "
            "every fact (machine names, places, numbers) and removing filler words. "
            'Respond {"description": string}.',
        )
        desc = str(result.get("description") or "").strip()
        return desc[:500] if desc else transcript[:500]
    except Exception as e:
        logger.warning("describe_from_transcript failed, using raw transcript: %s", e)
        return transcript[:500]


def _user_cap_key(kind: str, employee_id) -> str:
    return f"ai:usercap:{kind}:{now_ist().date().isoformat()}:{employee_id}"


async def user_daily_count(kind: str, employee_id) -> int:
    return int(await redis_client.get(_user_cap_key(kind, employee_id)) or 0)


async def incr_user_daily(kind: str, employee_id) -> None:
    key = _user_cap_key(kind, employee_id)
    n = await redis_client.incr(key)
    if n == 1:
        await redis_client.expire(key, 2 * 86400)


# ---------------- Redis cache + usage counters ----------------

def _cache_key(endpoint: str, resource_key: str) -> str:
    return f"ai:cache:{endpoint}:{resource_key}"


async def cache_get(endpoint: str, resource_key: str) -> dict | None:
    raw = await redis_client.get(_cache_key(endpoint, resource_key))
    if raw:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None
    return None


async def cache_set(endpoint: str, resource_key: str, payload: dict) -> None:
    await redis_client.set(
        _cache_key(endpoint, resource_key), json.dumps(payload), ex=settings.ai_cache_ttl
    )


def usage_key_prefix(is_demo: bool) -> str:
    """Demo AI calls are counted separately so real dashboards never include them."""
    return "ai:usage:demo" if is_demo else "ai:usage"


async def incr_usage(kind: str, is_demo: bool = False) -> None:
    key = f"{usage_key_prefix(is_demo)}:{now_ist().date().isoformat()}:{kind}"
    n = await redis_client.incr(key)
    if n == 1:
        await redis_client.expire(key, 8 * 86400)


async def usage_for_date(date_str: str, is_demo: bool = False) -> dict:
    counts: dict[str, int] = {}
    async for key in redis_client.scan_iter(f"{usage_key_prefix(is_demo)}:{date_str}:*"):
        kind = key.rsplit(":", 1)[-1]
        val = await redis_client.get(key)
        counts[kind] = int(val or 0)
    failures = await redis_client.get(f"rekognition:failures:{date_str}")
    return {"date": date_str, "counts": counts, "rekognition_failures": int(failures or 0)}
