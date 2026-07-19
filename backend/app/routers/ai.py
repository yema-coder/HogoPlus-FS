"""AI endpoints (Universal Key): ANPR, gauge reading, voice-fill, SOP RAG chat.

Design contract: every endpoint returns {value(s), confidence, model} and NEVER
blocks a user-facing submit — AI enriches, humans confirm. Identical calls are
cached 24h by (endpoint, photo_key).
"""
import logging
import re
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app import ai_core
from app.aws import RekognitionUnavailable, detect_text
from app.database import get_session
from app.models import ChatMessage, Employee, FormDefinition, SopChunk, SopDoc
from app.schemas import AnprIn, ChatIn, GaugeReadIn, VoiceFillIn
from app.security import get_approved_employee
from app.storage import get_storage

router = APIRouter(prefix="/ai", tags=["ai"])
logger = logging.getLogger("hogo.ai.router")

PLATE_REGEX = re.compile(r"^[A-Z]{2}[0-9]{1,2}[A-Z]{0,3}[0-9]{4}$")

CHAT_FALLBACK = {
    "en": "I could not find this in the uploaded SOP documents. Please ask about factory procedures covered in the SOPs.",
    "hi": "यह जानकारी अपलोड किए गए SOP दस्तावेज़ों में नहीं मिली। कृपया SOP में शामिल प्रक्रियाओं के बारे में पूछें।",
    "mr": "ही माहिती अपलोड केलेल्या SOP दस्तऐवजांत सापडली नाही. कृपया SOP मधील प्रक्रियांबद्दल विचारा.",
}
CHAT_DISTANCE_THRESHOLD = 0.78  # loose gate — the LLM prompt enforces strict grounding/honesty
LANG_NAME = {"en": "English", "hi": "Hindi", "mr": "Marathi"}


def _normalize_plate(raw: str | None) -> str:
    return re.sub(r"[^A-Z0-9]", "", (raw or "").upper())


def _get_bytes(key: str) -> bytes:
    storage = get_storage()
    try:
        return storage.get(key)
    except Exception:
        raise HTTPException(status_code=404, detail=f"File not found: {key}")


@router.post("/anpr")
async def anpr(
    body: AnprIn,
    employee: Employee = Depends(get_approved_employee),
):
    cached = await ai_core.cache_get("anpr", body.photo_key)
    if cached:
        return {**cached, "cached": True}

    image = await run_in_threadpool(_get_bytes, body.photo_key)
    plate, confidence, source = None, 0.0, "vision"

    try:
        result = await ai_core.vision_json(
            'Extract the Indian vehicle registration plate visible in this photo. '
            'Respond ONLY with JSON {"plate": string or null, "confidence": number between 0 and 1}. '
            "Plate format examples: MH12AB1234, MH09C4321.",
            image,
        )
        plate = _normalize_plate(result.get("plate"))
        confidence = float(result.get("confidence") or 0.0)
    except Exception as e:
        logger.warning("ANPR vision failed: %s", e)
    await ai_core.incr_usage("anpr", employee.is_demo)

    valid = bool(plate and PLATE_REGEX.match(plate))
    if not valid or confidence < 0.7:
        # fallback: Rekognition DetectText, re-validate against Indian plate regex
        try:
            lines = await run_in_threadpool(detect_text, image)
            await ai_core.incr_usage("anpr_detect_text", employee.is_demo)
            best = None
            for line in lines:
                cand = _normalize_plate(line["text"])
                if PLATE_REGEX.match(cand):
                    if best is None or line["confidence"] > best[1]:
                        best = (cand, line["confidence"])
            if best and (not valid or best[1] / 100.0 > confidence):
                plate, confidence, source, valid = best[0], round(best[1] / 100.0, 3), "rekognition_detect_text", True
        except RekognitionUnavailable:
            pass

    payload = {
        "plate": plate if valid else None,
        "confidence": round(confidence, 3) if valid else 0.0,
        "valid": valid,
        "source": source if valid else None,
        "model": ai_core.VISION_MODEL,
    }
    if valid:
        await ai_core.cache_set("anpr", body.photo_key, payload)
    return payload


@router.post("/gauge-read")
async def gauge_read(
    body: GaugeReadIn,
    employee: Employee = Depends(get_approved_employee),
):
    cached = await ai_core.cache_get("gauge_read", body.photo_key)
    if cached:
        payload = {**cached, "cached": True}
    else:
        image = await run_in_threadpool(_get_bytes, body.photo_key)
        value, confidence, unit = None, 0.0, None
        try:
            result = await ai_core.vision_json(
                "Read the numeric value shown on the gauge / meter / digital display in this photo. "
                'Respond ONLY with JSON {"value": number or null, "unit": string or null, '
                '"confidence": number between 0 and 1}.',
                image,
            )
            value = result.get("value")
            if value is not None:
                value = float(value)
            confidence = float(result.get("confidence") or 0.0)
            unit = result.get("unit")
        except Exception as e:
            logger.warning("Gauge read failed: %s", e)
        await ai_core.incr_usage("gauge_read", employee.is_demo)
        payload = {
            "value": value,
            "unit": unit,
            "confidence": round(confidence, 3),
            "model": ai_core.VISION_MODEL,
        }
        if value is not None:
            await ai_core.cache_set("gauge_read", body.photo_key, payload)

    # in_range computed per-request (expected range may differ between calls)
    in_range = None
    if payload.get("value") is not None:
        in_range = True
        if body.expected_min is not None and payload["value"] < body.expected_min:
            in_range = False
        if body.expected_max is not None and payload["value"] > body.expected_max:
            in_range = False
    return {**payload, "in_range": in_range}


@router.post("/voice-fill")
async def voice_fill(
    body: VoiceFillIn,
    employee: Employee = Depends(get_approved_employee),
    session: AsyncSession = Depends(get_session),
):
    form = await session.get(FormDefinition, body.form_definition_id)
    if form is None or not form.is_active:
        raise HTTPException(status_code=404, detail="Form not found")

    audio = await run_in_threadpool(_get_bytes, body.audio_key)
    ext = body.audio_key.rsplit(".", 1)[-1] if "." in body.audio_key else "m4a"
    try:
        transcript, language = await ai_core.transcribe_audio(audio, ext)
    except Exception as e:
        logger.warning("Voice-fill STT failed: %s", e)
        raise HTTPException(status_code=502, detail="Transcription failed")
    await ai_core.incr_usage("voice_fill", employee.is_demo)

    fillable = [
        {
            "key": f["key"],
            "type": f["type"],
            "label": f.get("label_en") or f["key"],
            "options": f.get("options"),
        }
        for f in form.schema_json.get("fields", [])
        if f.get("type") in ("text", "number", "select", "toggle")
    ]
    fields: dict = {}
    if transcript.strip() and fillable:
        try:
            import json as json_mod

            result = await ai_core.text_json(
                "You map a spoken factory-floor transcript to form fields. Respond ONLY with valid JSON.",
                "Form fields:\n"
                + json_mod.dumps(fillable, ensure_ascii=False)
                + f'\n\nTranscript ({LANG_NAME.get(language, language)}): "{transcript}"\n\n'
                'Return {"fields": {key: value}} containing ONLY the fields you can fill confidently '
                "from the transcript — omit uncertain ones entirely. Rules: number fields get numbers; "
                "select fields get exactly one of the allowed options (match meaning, return the option "
                "string verbatim); toggle fields get true/false; text fields get short text in the "
                "transcript's language.",
            )
            raw_fields = result.get("fields") or {}
            by_key = {f["key"]: f for f in fillable}
            for k, v in raw_fields.items():
                spec = by_key.get(k)
                if spec is None or v is None:
                    continue
                if spec["type"] == "number":
                    try:
                        fields[k] = float(v)
                    except (TypeError, ValueError):
                        continue
                elif spec["type"] == "select":
                    opts = spec.get("options") or []
                    match = next((o for o in opts if str(o).lower() == str(v).lower()), None)
                    if match is not None:
                        fields[k] = match
                elif spec["type"] == "toggle":
                    fields[k] = bool(v) if isinstance(v, bool) else str(v).lower() in ("true", "yes", "1")
                else:
                    fields[k] = str(v)
        except Exception as e:
            logger.warning("Voice-fill mapping failed: %s", e)

    return {
        "transcript": transcript,
        "language": language,
        "fields": fields,
        "model": ai_core.TEXT_MODEL,
    }


@router.post("/chat")
async def sop_chat(
    body: ChatIn,
    employee: Employee = Depends(get_approved_employee),
    session: AsyncSession = Depends(get_session),
):
    from app.embeddings import embed_query

    lang = employee.language_pref if employee.language_pref in ("en", "hi", "mr") else "mr"
    conversation_id = body.conversation_id or uuid.uuid4()

    # history: last 6 turns for context
    history = (
        (
            await session.execute(
                select(ChatMessage)
                .where(
                    ChatMessage.conversation_id == conversation_id,
                    ChatMessage.employee_id == employee.id,
                )
                .order_by(ChatMessage.created_at.desc())
                .limit(6)
            )
        )
        .scalars()
        .all()
    )
    history = list(reversed(history))

    session.add(
        ChatMessage(
            employee_id=employee.id, conversation_id=conversation_id,
            role="user", content=body.message, is_demo=employee.is_demo,
        )
    )

    qvec = await run_in_threadpool(embed_query, body.message)
    rows = (
        await session.execute(
            select(
                SopChunk.content,
                SopChunk.page,
                SopDoc.title,
                SopChunk.embedding.cosine_distance(qvec).label("dist"),
            )
            .join(SopDoc, SopChunk.doc_id == SopDoc.id)
            .where(SopDoc.status == "ready")
            .order_by(SopChunk.embedding.cosine_distance(qvec))
            .limit(6)
        )
    ).all()
    relevant = [r for r in rows if r.dist <= CHAT_DISTANCE_THRESHOLD]

    await ai_core.incr_usage("chat", employee.is_demo)

    if not relevant:
        answer, citations = CHAT_FALLBACK[lang], []
    else:
        context = "\n\n".join(
            f"[Doc: {r.title} | Page: {r.page}]\n{r.content}" for r in relevant
        )
        convo = "\n".join(f"{m.role}: {m.content}" for m in history) or "(none)"
        try:
            answer = await ai_core.chat_answer(
                f"You are Sahayak, the factory SOP assistant. Answer in {LANG_NAME[lang]} ONLY. "
                "Ground your answer STRICTLY in the provided SOP excerpts — never invent factory "
                "procedures. The question and the excerpts may be in different languages (Marathi/"
                "Hindi/English) — translate the meaning across languages when answering. "
                "Cite the document name and page for facts you use. Only if NONE of the excerpts "
                f'contain relevant information, reply exactly: "{CHAT_FALLBACK[lang]}"',
                f"Conversation so far:\n{convo}\n\nSOP excerpts:\n{context}\n\nQuestion: {body.message}",
            )
        except Exception as e:
            logger.warning("SOP chat LLM failed: %s", e)
            raise HTTPException(status_code=502, detail="Chat unavailable, try again")
        if answer.strip() == CHAT_FALLBACK[lang]:
            citations = []
        else:
            seen = set()
            citations = []
            for r in relevant:
                key = (r.title, r.page)
                if key not in seen:
                    seen.add(key)
                    citations.append({"doc_title": r.title, "page": r.page})

    session.add(
        ChatMessage(
            employee_id=employee.id, conversation_id=conversation_id,
            role="assistant", content=answer, citations=citations, is_demo=employee.is_demo,
        )
    )
    await session.commit()

    return {
        "conversation_id": str(conversation_id),
        "answer": answer,
        "citations": citations,
        "model": ai_core.CHAT_MODEL,
    }
