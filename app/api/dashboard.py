"""Owner dashboard for all candidates (passed or not)."""

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

    stats = _compute_stats(candidates)

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

        name = str(candidate.get("name") or "Unnamed")
        search_key = html.escape(
            " ".join(
                filter(None, [
                    name.lower(),
                    str(username or "").lower(),
                    str(candidate.get("score_band") or "").lower(),
                ])
            )
        )

        band_key = html.escape(str(candidate.get("score_band") or "none"))
        status_key = "completed" if candidate.get("status") == "completed" else "in_progress"

        rows.append(
            f'<tr data-search="{search_key}" data-band="{band_key}" data-status="{status_key}">'
            f"<td class=\"name-cell\">{html.escape(name)}</td>"
            f"<td>{_status_badge(candidate)}</td>"
            f"<td>{_score_badge(candidate)}</td>"
            f"<td>{availability_cell}</td>"
            f"<td>{resume_cell}</td>"
            f"<td>{contact}</td>"
            f"<td>{profile_cell}</td>"
            f"<td>{conversation_cell}</td>"
            "</tr>"
        )

    table_body = (
        "".join(rows)
        if rows
        else '<tr><td colspan="8" class="empty-state">No candidates yet.</td></tr>'
    )

    return (
        "<!doctype html><html><head><title>Talent Live</title>"
        f"{_STYLE}</head>"
        "<body>"
        "<div class=\"page\">"
        "<header class=\"page-header\">"
        "<h1>Candidates</h1>"
        "<div class=\"filters\">"
        "<input id=\"search\" type=\"text\" placeholder=\"Search by name, Telegram, or band...\" "
        "oninput=\"applyFilters()\">"
        "<select id=\"bandFilter\" onchange=\"applyFilters()\">"
        "<option value=\"\">All bands</option>"
        "<option value=\"strong\">Strong</option>"
        "<option value=\"borderline\">Borderline</option>"
        "<option value=\"weak\">Weak</option>"
        "<option value=\"none\">No score yet</option>"
        "</select>"
        "<select id=\"statusFilter\" onchange=\"applyFilters()\">"
        "<option value=\"\">All statuses</option>"
        "<option value=\"completed\">Completed</option>"
        "<option value=\"in_progress\">In progress</option>"
        "</select>"
        "</div>"
        "</header>"
        + _render_stats_bar(stats)
        + "<div class=\"table-card\">"
        "<div class=\"table-scroll\">"
        "<table><thead><tr>"
        "<th>Name</th><th>Status</th><th>Score</th><th>Availability</th>"
        "<th>Resume/Materials</th><th>Telegram</th><th>Full Profile</th>"
        "<th>Conversation</th>"
        "</tr></thead><tbody>"
        + table_body
        + "</tbody></table>"
        "</div></div></div>"
        "<script>"
        "function applyFilters() {"
        "  var query = document.getElementById('search').value.trim().toLowerCase();"
        "  var band = document.getElementById('bandFilter').value;"
        "  var status = document.getElementById('statusFilter').value;"
        "  document.querySelectorAll('tbody tr[data-search]').forEach(function (row) {"
        "    var matchesQuery = row.getAttribute('data-search').indexOf(query) !== -1;"
        "    var matchesBand = !band || row.getAttribute('data-band') === band;"
        "    var matchesStatus = !status || row.getAttribute('data-status') === status;"
        "    row.style.display = (matchesQuery && matchesBand && matchesStatus) ? '' : 'none';"
        "  });"
        "}"
        "</script>"
        "</body></html>"
    )


def _compute_stats(candidates: List[Dict[str, Any]]) -> Dict[str, int]:

    stats = {
        "total": len(candidates),
        "strong": 0,
        "borderline": 0,
        "weak": 0,
        "in_progress": 0,
    }

    for candidate in candidates:

        band = candidate.get("score_band")

        if band in stats:
            stats[band] += 1

        if candidate.get("status") != "completed":
            stats["in_progress"] += 1

    return stats


def _render_stats_bar(stats: Dict[str, int]) -> str:

    cards = [
        ("Total", stats["total"], "stat-total"),
        ("Strong", stats["strong"], "stat-strong"),
        ("Borderline", stats["borderline"], "stat-borderline"),
        ("Weak", stats["weak"], "stat-weak"),
        ("In progress", stats["in_progress"], "stat-progress"),
    ]

    items = "".join(
        f'<div class="stat {css}"><div class="stat-value">{value}</div>'
        f'<div class="stat-label">{html.escape(label)}</div></div>'
        for label, value, css in cards
    )

    return f'<div class="stats-bar">{items}</div>'


def _status_badge(candidate: Dict[str, Any]) -> str:

    status = candidate.get("status")
    stage = candidate.get("current_stage")

    stage_label = STAGE_LABELS.get(stage, f"Stage {stage}" if stage is not None else "Unknown")

    if status == "completed":
        return f'<span class="badge badge-completed">{html.escape(stage_label)}</span>'

    return f'<span class="badge badge-progress">In progress · {html.escape(stage_label)}</span>'


def _score_badge(candidate: Dict[str, Any]) -> str:

    score_value = candidate.get("total_score")
    band_value = candidate.get("score_band")

    band_css = {
        "strong": "badge-strong",
        "borderline": "badge-borderline",
        "weak": "badge-weak",
    }.get(band_value, "badge-none")

    if score_value is None:
        return f'<span class="badge {band_css}">No score yet</span>'

    band_label = html.escape(str(band_value)) if band_value else ""

    return (
        f'<span class="badge {band_css}">{html.escape(str(score_value))}/100'
        + (f" · {band_label}" if band_label else "")
        + "</span>"
    )


def _render_availability_cell(session_state: Dict[str, Any]) -> str:
    """
    The availability/work-stability answers, collapsed behind a
    <details> toggle like Full Profile and Conversation.
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

    return (
        "<details><summary>View availability</summary>"
        + "".join(parts)
        + "</details>"
    )


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


_STYLE = """<style>
:root {
  --bg: #f3f4f6;
  --card: #ffffff;
  --border: #e5e7eb;
  --text: #111827;
  --muted: #6b7280;
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--bg); color: var(--text);
  font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
}
.page { max-width: 1400px; margin: 0 auto; padding: 28px 24px 60px; }
.page-header {
  display: flex; align-items: center; justify-content: space-between;
  flex-wrap: wrap; gap: 12px; margin-bottom: 20px;
}
.page-header h1 { font-size: 1.4rem; margin: 0; }
.filters { display: flex; gap: 10px; flex-wrap: wrap; }
#search, #bandFilter, #statusFilter {
  border: 1px solid var(--border); border-radius: 8px; padding: 9px 14px;
  font: inherit; background: var(--card); color: var(--text);
}
#search { width: 280px; max-width: 100%; }
#search:focus, #bandFilter:focus, #statusFilter:focus {
  outline: 2px solid #6366f1; outline-offset: 1px;
}

.stats-bar {
  display: grid; grid-template-columns: repeat(5, 1fr); gap: 12px;
  margin-bottom: 20px;
}
.stat {
  background: var(--card); border: 1px solid var(--border); border-radius: 10px;
  padding: 14px 16px; border-left: 4px solid var(--muted);
}
.stat-value { font-size: 1.5rem; font-weight: 700; }
.stat-label { font-size: 0.8rem; color: var(--muted); margin-top: 2px; }
.stat-total { border-left-color: #6366f1; }
.stat-strong { border-left-color: #16a34a; }
.stat-borderline { border-left-color: #d97706; }
.stat-weak { border-left-color: #dc2626; }
.stat-progress { border-left-color: #6b7280; }

.table-card {
  background: var(--card); border: 1px solid var(--border); border-radius: 12px;
  overflow: hidden;
}
.table-scroll { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; min-width: 1100px; }
thead th {
  position: sticky; top: 0; background: #fafafa; text-align: left;
  font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.03em;
  color: var(--muted); padding: 12px 14px; border-bottom: 1px solid var(--border);
  white-space: nowrap;
}
tbody td {
  padding: 12px 14px; border-bottom: 1px solid var(--border); vertical-align: top;
}
tbody tr:nth-child(even) { background: #fbfbfc; }
tbody tr:hover { background: #f0f1ff; }
.name-cell { font-weight: 600; white-space: nowrap; }
.empty-state { text-align: center; color: var(--muted); padding: 40px !important; }

.badge {
  display: inline-block; padding: 3px 10px; border-radius: 999px;
  font-size: 0.8rem; font-weight: 600; white-space: nowrap;
}
.badge-strong { background: #dcfce7; color: #166534; }
.badge-borderline { background: #fef3c7; color: #92400e; }
.badge-weak { background: #fee2e2; color: #991b1b; }
.badge-none { background: #f3f4f6; color: #6b7280; }
.badge-completed { background: #dbeafe; color: #1e40af; }
.badge-progress { background: #f3f4f6; color: #4b5563; }

.not-submitted { color: #9ca3af; font-style: italic; }
.field-label { color: var(--muted); font-size: 0.85em; }
details summary { cursor: pointer; color: #4f46e5; font-size: 0.9em; }
dl { margin: 6px 0; }
dt { font-weight: 600; margin-top: 6px; }
dd { margin-left: 0; }
.chat {
  max-height: 320px; overflow-y: auto; min-width: 280px; max-width: 420px;
  margin-top: 6px;
}
.chat p { margin: 4px 0; padding: 6px 8px; border-radius: 6px; }
.chat .user { background: #eef2ff; }
.chat .assistant { background: #f4f4f4; }
.chat .role { font-weight: 600; font-size: 0.8em; display: block; color: var(--muted); }
</style>"""
