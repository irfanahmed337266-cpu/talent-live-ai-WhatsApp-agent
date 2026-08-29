"""Telegram webhook transport for the Talent Live interview engine."""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, BackgroundTasks, Request, Response

from app.agents.graph import run_agent
from app.agents.state import create_initial_state
from app.services import telegram as telegram_client
from app.services.supabase import (
    get_agent_session,
    has_processed_message,
    save_agent_session,
    save_candidate_material,
    save_interview_message,
    update_candidate,
    upsert_candidate,
)

router = APIRouter()

MAX_WEBHOOK_BYTES = 256 * 1024
MAX_TEXT_LENGTH = 4096

MEDIA_TYPES = ("document", "photo", "voice", "audio", "video")

# --------------------------------------------------------------------------
# PER-CHAT RATE LIMIT
#
# No real person types faster than this; a script flooding the bot does.
# In-memory and per-process, so it resets on restart and doesn't protect
# across multiple worker processes - it's a cheap flood throttle, not a
# security boundary. Dropped messages get no reply and no DB writes at
# all (not even a dedupe-table write), which is the point: the whole cost
# of a flood becomes one dict lookup.
# --------------------------------------------------------------------------

MIN_SECONDS_BETWEEN_MESSAGES = 1.5

_last_message_at: Dict[str, float] = {}


def _is_rate_limited(chat_id: str) -> bool:
    now = time.monotonic()
    last = _last_message_at.get(chat_id)
    _last_message_at[chat_id] = now
    return last is not None and (now - last) < MIN_SECONDS_BETWEEN_MESSAGES


@router.post("/telegram/webhook")
async def receive_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
) -> Dict[str, str]:
    if not telegram_client.webhook_secret_matches(
        request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    ):
        return Response(status_code=403)

    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_WEBHOOK_BYTES:
                return Response(status_code=413)
        except ValueError:
            return Response(status_code=400)

    try:
        payload = await request.json()
    except ValueError:
        return {"status": "ignored"}

    message = parse_update(payload)

    if message:
        background_tasks.add_task(process_message, message)

    return {"status": "received"}


def parse_update(payload: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(payload, dict):
        return None

    raw_message = payload.get("message")

    if not isinstance(raw_message, dict):
        return None

    sender = raw_message.get("from")
    chat = raw_message.get("chat")
    message_id = raw_message.get("message_id")

    if not isinstance(sender, dict) or not isinstance(chat, dict):
        return None

    chat_id = chat.get("id")

    if chat_id is None or message_id is None:
        return None

    text = raw_message.get("text")
    if isinstance(text, str) and len(text) > MAX_TEXT_LENGTH:
        text = text[:MAX_TEXT_LENGTH]
    message_type = "text" if isinstance(text, str) else "unsupported"

    media_file_id = None
    mime_type = None
    file_name = None

    if not isinstance(text, str):
        for media_type in MEDIA_TYPES:

            media = raw_message.get(media_type)

            if not media:
                continue

            message_type = media_type
            text = raw_message.get("caption")

            if media_type == "photo":
                # "photo" is a list of resolutions; the last entry is the
                # largest. Photos have no filename/mime_type of their own.
                if isinstance(media, list) and media:
                    media_file_id = media[-1].get("file_id")

            elif isinstance(media, dict):
                media_file_id = media.get("file_id")
                mime_type = media.get("mime_type")
                file_name = media.get("file_name")

            break

    return {
        "id": str(message_id),
        "chat_id": str(chat_id),
        "username": sender.get("username"),
        "type": message_type,
        "text": text,
        "media_file_id": media_file_id,
        "mime_type": mime_type,
        "file_name": file_name,
    }


def _already_completed_message(language: Optional[str]) -> str:

    if language == "roman_urdu":
        return (
            "Aap ka Talent Live screening pehle hi complete ho chuka hai. "
            "Shukriya! Agar fit bana to hum khud rabta karenge."
        )

    if language == "urdu":
        return (
            "آپ کی Talent Live screening پہلے ہی مکمل ہو چکی ہے۔ شکریہ! "
            "اگر fit بنا تو ہم خود رابطہ کریں گے۔"
        )

    return (
        "Your Talent Live screening is already complete. Thanks again! "
        "We'll reach out if there's a fit."
    )


def process_message(message: Dict[str, Any]) -> None:
    message_id = message["id"]
    chat_id = message["chat_id"]

    if _is_rate_limited(chat_id):
        return

    try:
        if has_processed_message(message_id):
            return

        session = get_agent_session(chat_id)

        if session and isinstance(session.get("state_json"), dict):
            state = session["state_json"]
        else:
            state = create_initial_state(phone_number=chat_id)

        state["phone_number"] = chat_id
        state["telegram_username"] = message.get("username")

        # --------------------------------------------------------------------
        # ALREADY COMPLETE
        #
        # Without this, every message sent after scoring finishes (even
        # "hello") re-triggers a full pipeline: run_agent() itself
        # short-circuits cheaply, but the closing message still gets
        # re-sent via Telegram, and the session/interview-message writes
        # still happen, on every single message, forever. Reply once with
        # a short notice, then go fully silent - no further Telegram
        # sends or Supabase writes for this chat.
        # --------------------------------------------------------------------

        if state.get("scoring_completed") is True:

            if not state.get("post_completion_notice_sent"):

                try:
                    telegram_client.send_text_message(
                        chat_id,
                        _already_completed_message(state.get("language")),
                    )
                except Exception as exc:
                    print(f"[telegram] failed to send completion notice: {type(exc).__name__}")

                state["post_completion_notice_sent"] = True

                try:
                    save_agent_session(chat_id, state, message_id=message_id)
                except Exception as exc:
                    print(f"[telegram] failed to save session: {type(exc).__name__}")

            return

        # Ensure a candidate row exists from the first message onward, not
        # just once Stage 3 starts (graph.py creates one lazily at that
        # point) - materials can arrive as early as Stage 2, and need a
        # candidate_id to attach to.
        if not state.get("candidate_id"):
            try:
                saved = upsert_candidate(chat_id, {})
                state["candidate_id"] = saved["id"]
            except Exception as exc:
                print(f"[telegram] failed to ensure candidate row: {type(exc).__name__}")

        user_text = message.get("text")

        if message["type"] in MEDIA_TYPES:

            candidate_id = state.get("candidate_id")

            if candidate_id:
                try:
                    save_candidate_material(
                        candidate_id,
                        {
                            "material_type": message["type"],
                            "media_file_id": message.get("media_file_id"),
                            "mime_type": message.get("mime_type"),
                            "file_name": message.get("file_name"),
                            "caption": message.get("text"),
                        },
                    )
                except Exception as exc:
                    print(f"[telegram] failed to save material: {type(exc).__name__}")

        if not isinstance(user_text, str) or not user_text.strip():
            user_text = "I sent an attachment." if message["type"] != "unsupported" else None

        if not user_text:
            return

        state["message"] = user_text
        state = run_agent(state)
        save_agent_session(chat_id, state, message_id=message_id)

        interview_id = state.get("interview_id")
        stage = int(state.get("stage", 0) or 0)

        if interview_id:
            save_interview_message(
                interview_id=interview_id,
                sender="candidate",
                message_text=user_text,
                message_type=message["type"],
                stage=stage,
                telegram_message_id=message_id,
            )

        candidate_id = state.get("candidate_id")
        if candidate_id and message.get("username"):
            update_candidate(
                candidate_id,
                {"telegram_username": message["username"]},
            )

        response_text = state.get("ai_response")

        if not isinstance(response_text, str) or not response_text.strip():
            return

        telegram_client.send_text_message(chat_id, response_text)

        if interview_id:
            save_interview_message(
                interview_id=interview_id,
                sender="assistant",
                message_text=response_text,
                stage=stage,
            )
    except Exception as exc:
        print(f"[telegram] message processing failed: {type(exc).__name__}")