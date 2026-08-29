"""Telegram Bot API client for the Talent Live screening agent."""

from __future__ import annotations

import os
import hmac
from typing import Any, Dict, List, Optional

import httpx
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET")


class TelegramConfigError(RuntimeError):
    """Raised when Telegram configuration is missing."""


class TelegramAPIError(RuntimeError):
    """Raised when the Telegram Bot API rejects a request."""


def _api_url(method: str) -> str:
    if not TELEGRAM_BOT_TOKEN:
        raise TelegramConfigError("TELEGRAM_BOT_TOKEN is not configured.")

    return f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}"


def send_text_message(chat_id: str, text: str) -> Dict[str, Any]:
    response = httpx.post(
        _api_url("sendMessage"),
        json={"chat_id": chat_id, "text": text},
        timeout=20.0,
    )

    if response.status_code >= 400:
        raise TelegramAPIError(
            f"Telegram API error {response.status_code}: {response.text}"
        )

    data = response.json()

    if not data.get("ok"):
        raise TelegramAPIError("Telegram returned an unsuccessful response.")

    return data


def get_updates(offset: Optional[int] = None, timeout: int = 30) -> List[Dict[str, Any]]:
    """
    Long-poll Telegram for new updates. Used by the local polling runner
    as a no-public-URL alternative to the webhook endpoint.
    """

    params: Dict[str, Any] = {"timeout": timeout}

    if offset is not None:
        params["offset"] = offset

    response = httpx.get(
        _api_url("getUpdates"),
        params=params,
        timeout=timeout + 10.0,
    )

    if response.status_code >= 400:
        raise TelegramAPIError(
            f"Telegram API error {response.status_code}: {response.text}"
        )

    data = response.json()

    if not data.get("ok"):
        raise TelegramAPIError("Telegram returned an unsuccessful response.")

    return data.get("result", [])


def delete_webhook() -> None:
    """
    Telegram refuses getUpdates while a webhook is registered (error 409).
    Call this once before polling to clear any previously configured
    webhook (e.g. from an earlier ngrok URL that no longer exists).
    """

    response = httpx.post(
        _api_url("deleteWebhook"),
        timeout=20.0,
    )

    if response.status_code >= 400:
        raise TelegramAPIError(
            f"Telegram API error {response.status_code}: {response.text}"
        )


def get_file_url(file_id: str) -> Optional[str]:
    """
    Resolve a Telegram file_id to a temporary download URL (valid ~1 hour).

    SECURITY NOTE: the returned URL embeds TELEGRAM_BOT_TOKEN in plain
    text (Telegram's file API requires this). Only render it somewhere
    already gated behind auth (e.g. the owner dashboard) - never expose
    it publicly or log it.
    """

    try:
        response = httpx.get(
            _api_url("getFile"),
            params={"file_id": file_id},
            timeout=20.0,
        )
    except Exception:
        return None

    if response.status_code >= 400:
        return None

    data = response.json()

    if not data.get("ok"):
        return None

    file_path = data.get("result", {}).get("file_path")

    if not file_path:
        return None

    return f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}"


def webhook_secret_matches(value: Optional[str]) -> bool:
    if not TELEGRAM_WEBHOOK_SECRET or not value:
        return False

    return hmac.compare_digest(
        TELEGRAM_WEBHOOK_SECRET,
        value,
    )