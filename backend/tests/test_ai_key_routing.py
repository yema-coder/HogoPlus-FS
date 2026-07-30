"""AI key routing (owner requirement, 2026-06): production AI must run on the
factory's OWN OpenAI account (OPENAI_API_KEY) — the Emergent universal key is
only a sandbox fallback. These tests prove EVERY AI call path (text/vision/chat
LLM, Whisper STT, TTS) picks the dedicated key when it is set, and falls back
cleanly when it is not. App-level daily caps stay in force in both modes.
"""
import pytest

from app import ai_core
from app.config import settings

pytestmark = pytest.mark.asyncio


# ---------------- route resolution ----------------

def test_llm_route_prefers_dedicated_openai_key(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "sk-user-own-account")
    monkeypatch.setattr(settings, "openai_model", "gpt-4o-mini")
    assert ai_core.llm_route() == ("sk-user-own-account", "openai", "gpt-4o-mini")
    assert ai_core.speech_key() == "sk-user-own-account"
    assert ai_core.active_model() == "gpt-4o-mini"


def test_llm_route_falls_back_to_emergent(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "")
    monkeypatch.setattr(settings, "emergent_llm_key", "sk-emergent-sandbox")
    assert ai_core.llm_route() == ("sk-emergent-sandbox", "gemini", ai_core.GEMINI_MODEL)
    assert ai_core.speech_key() == "sk-emergent-sandbox"


def test_openai_model_is_configurable(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "sk-user-own-account")
    monkeypatch.setattr(settings, "openai_model", "gpt-4.1-mini")
    assert ai_core.llm_route()[2] == "gpt-4.1-mini"


# ---------------- call paths actually use the routed key ----------------

class _FakeLlmChat:
    """Captures constructor + with_model args; returns valid JSON."""
    captured: list = []

    def __init__(self, api_key, session_id, system_message):
        self._rec = {"api_key": api_key}
        _FakeLlmChat.captured.append(self._rec)

    def with_model(self, provider, model):
        self._rec["provider"], self._rec["model"] = provider, model
        return self

    def with_params(self, **kw):
        return self

    async def send_message(self, msg):
        return '{"description": "ok", "ok": true}'


async def test_text_json_uses_dedicated_key(monkeypatch):
    _FakeLlmChat.captured = []
    monkeypatch.setattr(settings, "openai_api_key", "sk-user-own-account")
    monkeypatch.setattr("emergentintegrations.llm.chat.LlmChat", _FakeLlmChat)
    out = await ai_core.text_json("system", "prompt")
    assert out["ok"] is True
    rec = _FakeLlmChat.captured[-1]
    assert rec == {"api_key": "sk-user-own-account", "provider": "openai", "model": "gpt-4o-mini"}


async def test_vision_json_uses_dedicated_key(monkeypatch):
    _FakeLlmChat.captured = []
    monkeypatch.setattr(settings, "openai_api_key", "sk-user-own-account")
    monkeypatch.setattr("emergentintegrations.llm.chat.LlmChat", _FakeLlmChat)
    out = await ai_core.vision_json("prompt", b"\xff\xd8\xffimg")
    assert out["ok"] is True
    rec = _FakeLlmChat.captured[-1]
    assert rec["api_key"] == "sk-user-own-account"
    assert (rec["provider"], rec["model"]) == ("openai", "gpt-4o-mini")


async def test_chat_answer_uses_dedicated_key(monkeypatch):
    _FakeLlmChat.captured = []
    monkeypatch.setattr(settings, "openai_api_key", "sk-user-own-account")
    monkeypatch.setattr("emergentintegrations.llm.chat.LlmChat", _FakeLlmChat)
    out = await ai_core.chat_answer("system", "prompt")
    assert out  # plain text passthrough
    assert _FakeLlmChat.captured[-1]["api_key"] == "sk-user-own-account"


async def test_chat_paths_fall_back_to_emergent_key(monkeypatch):
    _FakeLlmChat.captured = []
    monkeypatch.setattr(settings, "openai_api_key", "")
    monkeypatch.setattr(settings, "emergent_llm_key", "sk-emergent-sandbox")
    monkeypatch.setattr("emergentintegrations.llm.chat.LlmChat", _FakeLlmChat)
    await ai_core.text_json("system", "prompt")
    rec = _FakeLlmChat.captured[-1]
    assert rec == {"api_key": "sk-emergent-sandbox", "provider": "gemini", "model": ai_core.GEMINI_MODEL}


async def test_whisper_stt_uses_dedicated_key(monkeypatch):
    captured = {}

    class FakeSTT:
        def __init__(self, api_key):
            captured["api_key"] = api_key

        async def transcribe(self, f, **kw):
            class R:
                text = "नमस्कार"
                language = "marathi"
            return R()

    monkeypatch.setattr(settings, "openai_api_key", "sk-user-own-account")
    monkeypatch.setattr(
        "emergentintegrations.llm.openai.speech_to_text.OpenAISpeechToText", FakeSTT
    )
    transcript, lang = await ai_core.transcribe_audio(b"audio", "m4a")
    assert transcript == "नमस्कार" and lang == "mr"
    assert captured["api_key"] == "sk-user-own-account"


async def test_tts_uses_dedicated_key(monkeypatch):
    captured = {}

    class FakeTTS:
        def __init__(self, api_key):
            captured["api_key"] = api_key

        async def generate_speech(self, **kw):
            captured["model"] = kw.get("model")
            return b"ID3fake"

    monkeypatch.setattr(settings, "openai_api_key", "sk-user-own-account")
    monkeypatch.setattr(
        "emergentintegrations.llm.openai.text_to_speech.OpenAITextToSpeech", FakeTTS
    )
    audio = await ai_core.synthesize_speech("नमस्कार")
    assert audio == b"ID3fake"
    assert captured["api_key"] == "sk-user-own-account"
    assert captured["model"] == ai_core.TTS_MODEL
