"""
Web-based chat transport for the Talent Live interview engine.

For candidates in regions where Telegram is blocked (e.g. Pakistan) -
same interview engine (run_agent), same session persistence, just
reachable over a plain web page instead of a Telegram bot. Rides on
whatever FastAPI app this router gets mounted into (the same one
already deployed for the owner dashboard), so it needs no new hosting
or third-party approval - it goes live the moment this is deployed.

Known limitation (v1): no file upload for materials (CV/portfolio).
Candidates can still say "I don't have anything" or "I can just talk" -
the existing materials-stage text detection already handles that.
"""

from __future__ import annotations

import json
import re
import time
from typing import Dict, Optional

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

from app.agents.graph import run_agent
from app.agents.state import create_initial_state
from app.services.supabase import (
    get_agent_session,
    save_agent_session,
    upsert_candidate,
)

router = APIRouter(prefix="/webchat")

MAX_MESSAGE_LENGTH = 4096

# Mirrors app/api/telegram.py's MAX_WEBHOOK_BYTES check - reject an
# oversized body before it's fully read into memory, not after.
MAX_BODY_BYTES = 32 * 1024

# Browser-generated crypto.randomUUID() shape - reject anything else so a
# malformed/garbage session id can't be used to probe arbitrary keys.
SESSION_ID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)

# --------------------------------------------------------------------------
# RATE LIMITING
#
# Two layers, both in-memory/per-process (cheap deterrents, not a security
# boundary - see app/api/telegram.py's identical caveat):
#
# - Per-session: same as Telegram's per-chat throttle.
# - Per-IP: Telegram's per-chat throttle is enough on its own there because
#   a chat_id is a real Telegram account, not something an attacker can
#   mint on demand. Here, session_id is 100% client-generated with no
#   authentication - anyone can bypass a per-session-only limit just by
#   generating a new UUID per request. The per-IP layer closes that.
#   X-Forwarded-For is trusted here because this only runs behind Render's
#   proxy, which sets it; it would not be safe to trust on a deployment
#   directly exposed to the internet without a proxy in front of it.
# --------------------------------------------------------------------------

MIN_SECONDS_BETWEEN_MESSAGES = 1.5
MIN_SECONDS_BETWEEN_IP_REQUESTS = 0.5

_last_message_at: Dict[str, float] = {}
_last_request_at_by_ip: Dict[str, float] = {}

# Bound the rate-limit dicts' memory growth - an attacker rotating
# session ids/IPs forever would otherwise grow these unboundedly. Not a
# precise LRU, just a cheap periodic purge of stale entries.
_MAX_TRACKED_KEYS = 5000
_STALE_AFTER_SECONDS = 300


def _purge_stale(bucket: Dict[str, float]) -> None:
    if len(bucket) <= _MAX_TRACKED_KEYS:
        return
    now = time.monotonic()
    stale = [k for k, t in bucket.items() if now - t > _STALE_AFTER_SECONDS]
    for k in stale:
        bucket.pop(k, None)


def _is_rate_limited(session_key: str) -> bool:
    _purge_stale(_last_message_at)
    now = time.monotonic()
    last = _last_message_at.get(session_key)
    _last_message_at[session_key] = now
    return last is not None and (now - last) < MIN_SECONDS_BETWEEN_MESSAGES


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _is_ip_rate_limited(request: Request, bucket_name: str) -> bool:
    # bucket_name keeps /message and /history on separate cooldowns, so a
    # normal page load (history fetch immediately followed by the first
    # /start message) can't trip a shared timer meant for flooding, not
    # for one legitimate user's own sequential requests.
    _purge_stale(_last_request_at_by_ip)
    key = f"{bucket_name}:{_client_ip(request)}"
    now = time.monotonic()
    last = _last_request_at_by_ip.get(key)
    _last_request_at_by_ip[key] = now
    return last is not None and (now - last) < MIN_SECONDS_BETWEEN_IP_REQUESTS


def _already_completed_message(language: Optional[str]) -> str:
    # Deliberately duplicated from app/api/telegram.py's
    # _already_completed_message - small, transport-specific text, not
    # worth cross-importing for.
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


@router.post("/message")
async def send_message(request: Request) -> JSONResponse:

    if _is_ip_rate_limited(request, "message"):
        return JSONResponse({"error": "rate limited"}, status_code=429)

    # Check the declared size before reading the body into memory at
    # all - a client can lie about Content-Length, so this is paired
    # with the actual-length check right after, not a substitute for it.
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_BODY_BYTES:
                return JSONResponse({"error": "payload too large"}, status_code=413)
        except ValueError:
            return JSONResponse({"error": "invalid content-length"}, status_code=400)

    raw_body = await request.body()

    if len(raw_body) > MAX_BODY_BYTES:
        return JSONResponse({"error": "payload too large"}, status_code=413)

    try:
        payload = json.loads(raw_body or b"{}")
    except ValueError:
        return JSONResponse({"error": "invalid json"}, status_code=400)

    if not isinstance(payload, dict):
        return JSONResponse({"error": "invalid payload"}, status_code=400)

    session_id = str(payload.get("session_id") or "").strip()
    user_text = payload.get("message")

    if not SESSION_ID_PATTERN.match(session_id):
        return JSONResponse({"error": "invalid session"}, status_code=400)

    if not isinstance(user_text, str) or not user_text.strip():
        return JSONResponse({"error": "empty message"}, status_code=400)

    user_text = user_text.strip()[:MAX_MESSAGE_LENGTH]

    # "web:" prefix keeps this namespace distinct from real Telegram
    # chat_ids (plain integers-as-strings) in the same agent_sessions/
    # candidates tables.
    chat_key = f"web:{session_id}"

    if _is_rate_limited(chat_key):
        return JSONResponse({"error": "rate limited"}, status_code=429)

    try:
        session = get_agent_session(chat_key)
    except Exception as exc:
        print(f"[webchat] failed to load session: {type(exc).__name__}: {exc}")
        session = None

    if session and isinstance(session.get("state_json"), dict):
        state = session["state_json"]
    else:
        state = create_initial_state(phone_number=chat_key)

    if not state.get("candidate_id"):
        try:
            saved = upsert_candidate(chat_key, {})
            state["candidate_id"] = saved["id"]
        except Exception as exc:
            print(f"[webchat] failed to ensure candidate row: {type(exc).__name__}: {exc}")

    # Same post-completion silence as the Telegram transport - once
    # scoring is done, reply once more with a short notice, then stop.
    if state.get("scoring_completed") is True:

        if not state.get("post_completion_notice_sent"):

            notice = _already_completed_message(state.get("language"))
            state["post_completion_notice_sent"] = True

            try:
                save_agent_session(chat_key, state)
            except Exception as exc:
                print(f"[webchat] failed to save session: {type(exc).__name__}: {exc}")

            return JSONResponse({"reply": notice})

        return JSONResponse({"reply": None})

    state["message"] = user_text
    state["phone_number"] = chat_key

    try:
        state = run_agent(state)
    except Exception as exc:
        print(f"[webchat] run_agent failed: {type(exc).__name__}: {exc}")
        return JSONResponse({"error": "internal error"}, status_code=500)

    try:
        save_agent_session(chat_key, state)
    except Exception as exc:
        print(f"[webchat] failed to save session: {type(exc).__name__}: {exc}")

    return JSONResponse({"reply": state.get("ai_response")})


@router.get("/history")
def get_history(request: Request, session_id: str = "") -> JSONResponse:
    """
    Returns any existing conversation for this session without running
    the agent - used on page load so a reload/return visit doesn't
    re-send "/start" into a mid-interview session (which would get
    recorded as the answer to whatever question was pending).
    """

    if _is_ip_rate_limited(request, "history"):
        return JSONResponse({"history": []}, status_code=429)

    session_id = (session_id or "").strip()

    if not SESSION_ID_PATTERN.match(session_id):
        return JSONResponse({"history": []})

    chat_key = f"web:{session_id}"

    try:
        session = get_agent_session(chat_key)
    except Exception as exc:
        print(f"[webchat] failed to load history: {type(exc).__name__}: {exc}")
        return JSONResponse({"history": []})

    if not session or not isinstance(session.get("state_json"), dict):
        return JSONResponse({"history": []})

    history = session["state_json"].get("conversation_history")

    if not isinstance(history, list):
        history = []

    return JSONResponse({"history": history})


@router.get("", response_class=HTMLResponse)
def chat_page() -> str:
    return _CHAT_PAGE_HTML


_CHAT_PAGE_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Talent Live</title>
<style>
  :root { color-scheme: light; }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: #f4f5f7; font-family: system-ui, -apple-system, sans-serif;
    display: flex; justify-content: center;
  }
  .app {
    width: 100%; max-width: 640px; min-height: 100vh; background: #fff;
    display: flex; flex-direction: column;
  }
  header {
    padding: 16px 20px; border-bottom: 1px solid #e5e7eb; background: #111827; color: #fff;
  }
  header h1 { margin: 0; font-size: 1.1rem; }
  header p { margin: 4px 0 0; font-size: 0.85rem; color: #cbd5e1; }
  #log {
    flex: 1; overflow-y: auto; padding: 16px; display: flex; flex-direction: column; gap: 10px;
  }
  .msg { max-width: 80%; padding: 10px 14px; border-radius: 12px; line-height: 1.4; white-space: pre-wrap; }
  .msg.bot { background: #eef2ff; align-self: flex-start; border-bottom-left-radius: 2px; }
  .msg.user { background: #111827; color: #fff; align-self: flex-end; border-bottom-right-radius: 2px; }
  .msg.system { align-self: center; color: #888; font-size: 0.8rem; font-style: italic; }
  form {
    display: flex; gap: 8px; padding: 12px; border-top: 1px solid #e5e7eb; background: #fff;
  }
  textarea {
    flex: 1; resize: none; border: 1px solid #d1d5db; border-radius: 8px; padding: 10px 12px;
    font: inherit; max-height: 120px;
  }
  button {
    background: #111827; color: #fff; border: none; border-radius: 8px; padding: 0 20px;
    font: inherit; cursor: pointer;
  }
  button:disabled { opacity: 0.5; cursor: default; }
</style>
</head>
<body>
<div class="app">
  <header>
    <h1>Talent Live</h1>
    <p>Type a message to begin.</p>
  </header>
  <div id="log"></div>
  <form id="form">
    <textarea id="input" rows="1" placeholder="Type your message..." autofocus></textarea>
    <button id="send" type="submit">Send</button>
  </form>
</div>
<script>
(function () {
  var STORAGE_KEY = "talent_live_session_id";
  var sessionId = localStorage.getItem(STORAGE_KEY);
  if (!sessionId) {
    sessionId = crypto.randomUUID();
    localStorage.setItem(STORAGE_KEY, sessionId);
  }

  var log = document.getElementById("log");
  var form = document.getElementById("form");
  var input = document.getElementById("input");
  var sendBtn = document.getElementById("send");

  function addMessage(text, cls) {
    var el = document.createElement("div");
    el.className = "msg " + cls;
    el.textContent = text;
    log.appendChild(el);
    log.scrollTop = log.scrollHeight;
  }

  function setBusy(busy) {
    sendBtn.disabled = busy;
    input.disabled = busy;
  }

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    var text = input.value.trim();
    if (!text) return;

    addMessage(text, "user");
    input.value = "";
    setBusy(true);

    fetch("/webchat/message", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, message: text })
    })
      .then(function (res) { return res.json(); })
      .then(function (data) {
        if (data.reply) {
          addMessage(data.reply, "bot");
        } else if (data.error) {
          addMessage("Something went wrong. Please try again.", "system");
        }
      })
      .catch(function () {
        addMessage("Connection error. Please try again.", "system");
      })
      .finally(function () {
        setBusy(false);
        input.focus();
      });
  });

  input.addEventListener("keydown", function (event) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      form.requestSubmit();
    }
  });

  // On load: replay existing history if this session already has one
  // (a reload or return visit), otherwise kick off the conversation
  // fresh, same as a candidate tapping "Start" on Telegram. Never
  // re-send "/start" into an existing session - it would get recorded
  // as the answer to whatever question was pending.
  setBusy(true);
  fetch("/webchat/history?session_id=" + encodeURIComponent(sessionId))
    .then(function (res) { return res.json(); })
    .then(function (data) {
      var history = data.history || [];

      if (history.length > 0) {
        history.forEach(function (item) {
          addMessage(item.content, item.role === "user" ? "user" : "bot");
        });
        setBusy(false);
        return;
      }

      return fetch("/webchat/message", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId, message: "/start" })
      })
        .then(function (res) { return res.json(); })
        .then(function (data) {
          if (data.reply) addMessage(data.reply, "bot");
        })
        .finally(function () {
          setBusy(false);
        });
    })
    .catch(function () {
      setBusy(false);
    });
})();
</script>
</body>
</html>
"""
