"""Small owner dashboard for candidates who passed screening."""

from __future__ import annotations

import html
import hmac
import os
from typing import Any, Dict, List

from dotenv import load_dotenv
from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import HTMLResponse

from app.services import telegram as telegram_client
from app.services.supabase import (
    get_agent_sessions_for_candidates,
    get_all_candidates,
    get_materials_for_candidates,
)

# Talent Live's own stage numbers (app/agents/state.py) - used to render a
# human-readable "Status" column instead of a bare integer.
STAGE_LABELS = {
    0: "Just started",
    1: "Basic info",
    2: "Materials",
    3: "Interview",
    4: "Model explanation",
    5: "Completed",
}

# Matches the fixed order of the 4 "family"-category questions in
# app/agents/interview.py's QUESTION_BANK (reworded to be professional -
# see HANDOFF.md). interview["family_evidence"] holds the raw answers in
# this same order, one per question actually asked.
FAMILY_EVIDENCE_LABELS = [
    "Weekly availability",
    "Other commitments",
    "Setup stability",
    "Work environment",
]

load_dotenv()

router = APIRouter(prefix="/owner")


def _authorize(token: str | None) -> None:
    expected = os.getenv("DASHBOARD_TOKEN")
    if (
        not expected
        or not token
        or not hmac.compare_digest(token, expected)
    ):
        raise HTTPException(status_code=401, detail="Unauthorized")


def _resolve_token(
    authorization: str | None,
    token: str | None,
) -> str | None:
    if authorization:
        return authorization.removeprefix("Bearer ")
    return token


@router.get("/candidates", response_model=List[Dict[str, Any]])
def all_candidates_json(
    authorization: str | None = Header(default=None),
    token: str | None = Query(default=None),
) -> List[Dict[str, Any]]:
    _authorize(_resolve_token(authorization, token))
    return get_all_candidates()


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(
    authorization: str | None = Header(default=None),
    token: str | None = Query(default=None),
) -> str:
    # A plain browser visit can't set an Authorization header, so this
    # endpoint also accepts ?token=... as a link-friendly fallback.
    _authorize(_resolve_token(authorization, token))
    candidates = get_all_candidates()

    candidate_ids = [
        c["id"] for c in candidates if c.get("id")
    ]
    materials_by_candidate = get_materials_for_candidates(candidate_ids)
    sessions_by_candidate = get_agent_sessions_for_candidates(candidate_ids)

    rows = []

    for candidate in candidates:
        username = candidate.get("telegram_username")
        contact = (
            f'<a href="https://t.me/{html.escape(username)}">@{html.escape(username)}</a>'
            if username
            else html.escape(str(candidate.get("telegram_chat_id", "")))
        )

        materials = materials_by_candidate.get(candidate.get("id"), [])
        resume_cell = _render_materials_cell(materials)

        session_state = sessions_by_candidate.get(candidate.get("id"), {})
        availability_cell = _render_availability_cell(session_state)
        profile_cell = _render_profile_details(session_state)
        conversation_cell = _render_conversation_cell(session_state)
        status_cell = _render_status_cell(candidate)

        score_value = candidate.get("total_score")
        band_value = candidate.get("score_band")

        rows.append(
            "<tr>"
            f"<td>{html.escape(str(candidate.get('name') or 'Unnamed'))}</td>"
            f"<td>{status_cell}</td>"
            f"<td>{html.escape(str(score_value)) if score_value is not None else '—'}</td>"
            f"<td>{html.escape(str(band_value)) if band_value else '—'}</td>"
            f"<td>{availability_cell}</td>"
            f"<td>{resume_cell}</td>"
            f"<td>{contact}</td>"
            f"<td>{profile_cell}</td>"
            f"<td>{conversation_cell}</td>"
            "</tr>"
        )

    return (
        "<!doctype html><html><head><title>Talent Live</title>"
        "<style>body{font-family:system-ui;margin:40px}table{border-collapse:collapse;width:100%}"
        "th,td{padding:12px;border-bottom:1px solid #ddd;text-align:left;vertical-align:top}"
        ".not-submitted{color:#888;font-style:italic}"
        ".field-label{color:#666;font-size:0.85em}"
        "details summary{cursor:pointer;color:#06c}"
        "dl{margin:6px 0}dt{font-weight:600;margin-top:6px}dd{margin-left:0}"
        ".chat{max-height:320px;overflow-y:auto;min-width:280px;max-width:420px}"
        ".chat p{margin:4px 0;padding:6px 8px;border-radius:6px}"
        ".chat .user{background:#eef2ff}"
        ".chat .assistant{background:#f4f4f4}"
        ".chat .role{font-weight:600;font-size:0.8em;display:block;color:#666}"
        "</style></head>"
        "<body><h1>All candidates</h1><table><tr><th>Name</th><th>Status</th>"
        "<th>Score</th><th>Band</th><th>Availability</th><th>Resume/Materials</th>"
        "<th>Telegram</th><th>Full Profile</th><th>Conversation</th></tr>"
        + "".join(rows)
        + "</table></body></html>"
    )


def _render_status_cell(candidate: Dict[str, Any]) -> str:

    status = candidate.get("status")
    stage = candidate.get("current_stage")

    stage_label = STAGE_LABELS.get(stage, f"Stage {stage}" if stage is not None else "Unknown")

    if status == "completed":
        return html.escape(stage_label)

    return html.escape(f"In progress ({stage_label})")


def _render_availability_cell(session_state: Dict[str, Any]) -> str:
    """
    Surface the availability/work-stability answers directly in the main
    table (not tucked behind the details toggle), since that's the field
    most likely to affect whether/when someone actually gets contacted.
    """

    interview = session_state.get("interview", {}) or {}
    family_evidence = interview.get("family_evidence", [])

    if not isinstance(family_evidence, list) or not family_evidence:
        return '<span class="not-submitted">Not answered</span>'

    parts = []

    for label, answer in zip(FAMILY_EVIDENCE_LABELS, family_evidence):
        parts.append(
            f'<div><span class="field-label">{html.escape(label)}:</span> '
            f'{html.escape(str(answer))}</div>'
        )

    return "".join(parts)


def _render_profile_details(session_state: Dict[str, Any]) -> str:
    """
    Everything else extracted during the interview, collapsed behind a
    native <details> toggle so the main table stays scannable.
    """

    candidate = session_state.get("candidate", {}) or {}
    interview = session_state.get("interview", {}) or {}

    def field(label: str, value: Any) -> str:
        if isinstance(value, list):
            value = ", ".join(str(v) for v in value if v)
        if not value:
            return ""
        return (
            f"<dt>{html.escape(label)}</dt>"
            f"<dd>{html.escape(str(value))}</dd>"
        )

    items = "".join([
        field("Current job", candidate.get("current_job")),
        field("Experience", candidate.get("experience")),
        field("Skills", candidate.get("skills")),
        field("Work history", candidate.get("work_history")),
        field("Education", candidate.get("education")),
        field(
            "Additional info",
            candidate.get("additional_information")
            or interview.get("open_talk_evidence"),
        ),
    ])

    if not items:
        return '<span class="not-submitted">No further details</span>'

    return (
        "<details><summary>View</summary><dl>"
        + items
        + "</dl></details>"
    )


def _render_conversation_cell(session_state: Dict[str, Any]) -> str:
    """
    Full message-by-message transcript, from state["conversation_history"]
    (built up by graph.py's response_node on every turn, starting at
    message 1 - this covers the whole conversation including Stage 1/2,
    not just the Stage 3 interview, and needs no separate DB join since
    it's already in the same agent_sessions blob fetched for the other
    columns). Collapsed behind a <details> toggle like Full Profile.
    """

    history = session_state.get("conversation_history")

    if not isinstance(history, list) or not history:
        return '<span class="not-submitted">No messages yet</span>'

    lines = []

    for item in history:

        if not isinstance(item, dict):
            continue

        role = item.get("role")
        content = item.get("content")

        if not content:
            continue

        role_label = "Candidate" if role == "user" else "Bot"
        css_class = "user" if role == "user" else "assistant"

        lines.append(
            f'<p class="{css_class}">'
            f'<span class="role">{html.escape(role_label)}</span>'
            f"{html.escape(str(content))}"
            "</p>"
        )

    if not lines:
        return '<span class="not-submitted">No messages yet</span>'

    return (
        "<details><summary>View conversation "
        f"({len(lines)})</summary><div class=\"chat\">"
        + "".join(lines)
        + "</div></details>"
    )


def _render_materials_cell(materials: List[Dict[str, Any]]) -> str:
    """
    Render the Resume/Materials column.

    NOTE: candidates aren't asked for a "resume" specifically - Stage 2
    invites a CV/GitHub/portfolio/certificates/anything, as one open
    invitation. Whatever they attached (of any type) shows up here;
    there's no way to know which one, if any, is specifically a resume.
    Each link is a temporary (~1hr) Telegram file URL, resolved fresh on
    every dashboard load.
    """

    if not materials:
        return '<span class="not-submitted">Not submitted</span>'

    links = []

    for index, material in enumerate(materials, start=1):
        file_id = material.get("media_file_id")
        label = html.escape(
            material.get("file_name")
            or material.get("material_type")
            or f"file {index}"
        )

        url = telegram_client.get_file_url(file_id) if file_id else None

        if url:
            links.append(f'<a href="{html.escape(url)}">{label}</a>')
        else:
            links.append(f"{label} (unavailable)")

    return " · ".join(links)