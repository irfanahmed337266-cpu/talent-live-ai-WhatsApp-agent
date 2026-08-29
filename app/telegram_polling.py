"""
Long-polling runner for the Telegram bot.

This is an alternative transport to app/api/telegram.py's webhook endpoint:
instead of Telegram pushing updates to a public HTTPS URL, this process
pulls updates from Telegram directly. No public URL, no ngrok, no webhook
registration needed - just outbound HTTPS to api.telegram.org.

Reuses parse_update()/process_message() from app.api.telegram unchanged,
so both transports share identical message handling.

Local usage:
    python -m app.telegram_polling

Production usage:
    Deploy as a Render "Background Worker" (see render.yaml) with the same
    start command. A worker has no open port, so it needs no domain/TLS.
"""

from __future__ import annotations

import time

from app.api.telegram import parse_update, process_message
from app.services import telegram as telegram_client


def run_polling_loop() -> None:

    telegram_client.delete_webhook()

    print("[telegram] webhook cleared, starting long-polling...")

    offset = None

    while True:

        try:
            updates = telegram_client.get_updates(offset=offset, timeout=30)

        except Exception as exc:
            print(f"[telegram] getUpdates failed: {type(exc).__name__}: {exc}")
            time.sleep(5)
            continue

        for update in updates:

            offset = update["update_id"] + 1

            message = parse_update(update)

            if message:
                process_message(message)


if __name__ == "__main__":
    run_polling_loop()
