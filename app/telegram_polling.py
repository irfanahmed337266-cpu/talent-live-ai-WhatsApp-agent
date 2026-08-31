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

    # This used to be unprotected: if it raised for any reason (a network
    # hiccup, DNS issue, firewall/antivirus interference - anything
    # machine-specific), the whole process crashed before ever reaching
    # the polling loop below, which does have its own retry logic. The
    # supervisor script would then restart it 5s later, only to crash
    # again the same way - a fast, mostly-silent crash loop that still
    # occasionally opens a getUpdates connection just long enough to
    # collide with another poller, without making real progress.
    try:
        telegram_client.delete_webhook()
    except Exception as exc:
        print(f"[telegram] delete_webhook failed (continuing anyway): {type(exc).__name__}: {exc}")

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

            try:
                message = parse_update(update)

                if message:
                    process_message(message)

            except Exception as exc:
                print(f"[telegram] failed to handle update {update.get('update_id')}: {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    run_polling_loop()
