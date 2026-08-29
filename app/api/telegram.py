"""Telegram webhook transport for the Talent Live interview engine."""

from __future__ import annotations

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


def process_message(message: Dict[str, Any]) -> None:
    message_id = message["id"]

    try:
        if has_processed_message(message_id):
            return

        chat_id = message["chat_id"]
        session = get_agent_session(chat_id)

        if session and isinstance(session.get("state_json"), dict):
            state = session["state_json"]
        else:
            state = create_initial_state(phone_number=chat_id)

        state["phone_number"] = chat_id
        state["telegram_username"] = message.get("username")

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