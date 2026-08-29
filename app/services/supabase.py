import os
from typing import Any, Dict, Optional

from dotenv import load_dotenv
from supabase import create_client, Client


load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")


if not SUPABASE_URL:
    raise RuntimeError("SUPABASE_URL is missing from .env")

if not SUPABASE_KEY:
    raise RuntimeError("SUPABASE_KEY is missing from .env")


supabase: Client = create_client(
    SUPABASE_URL,
    SUPABASE_KEY,
)


# ============================================================================
# CANDIDATE
# ============================================================================

def upsert_candidate(
    phone_number: Optional[str],
    candidate: Dict[str, Any],
) -> Dict[str, Any]:

    data = {
        "telegram_chat_id": phone_number,
        **candidate,
    }

    response = (
        supabase
        .table("candidates")
        .upsert(
            data,
            on_conflict="telegram_chat_id",
        )
        .execute()
    )

    if not response.data:
        raise RuntimeError(
            "Supabase did not return candidate data."
        )

    return response.data[0]


def update_candidate(
    candidate_id: str,
    updates: Dict[str, Any],
) -> Dict[str, Any]:

    response = (
        supabase
        .table("candidates")
        .update(updates)
        .eq("id", candidate_id)
        .execute()
    )

    if not response.data:
        raise RuntimeError(
            "Supabase did not return updated candidate data."
        )

    return response.data[0]


def get_candidate_by_phone(
    phone_number: str,
) -> Optional[Dict[str, Any]]:

    response = (
        supabase
        .table("candidates")
        .select("*")
        .eq("telegram_chat_id", phone_number)
        .limit(1)
        .execute()
    )

    if not response.data:
        return None

    return response.data[0]


def get_candidate_by_id(
    candidate_id: str,
) -> Optional[Dict[str, Any]]:

    response = (
        supabase
        .table("candidates")
        .select("*")
        .eq("id", candidate_id)
        .limit(1)
        .execute()
    )

    if not response.data:
        return None

    return response.data[0]


# ============================================================================
# CANDIDATE MATERIALS
# ============================================================================

def save_candidate_material(
    candidate_id: str,
    material: Dict[str, Any],
) -> Dict[str, Any]:

    data = {
        "candidate_id": candidate_id,
        **material,
    }

    response = (
        supabase
        .table("candidate_materials")
        .insert(data)
        .execute()
    )

    if not response.data:
        raise RuntimeError(
            "Supabase did not return candidate material data."
        )

    return response.data[0]


def get_agent_sessions_for_candidates(
    candidate_ids: list[str],
) -> Dict[str, Dict[str, Any]]:
    """
    Batch-fetch agent_sessions.state_json for a set of candidate ids,
    keyed by candidate_id. This is where the actual candidate profile
    lives (skills, availability answers, etc.) - the candidates table
    itself only stores a handful of summary columns.
    """

    if not candidate_ids:
        return {}

    response = (
        supabase
        .table("agent_sessions")
        .select("candidate_id, state_json")
        .in_("candidate_id", candidate_ids)
        .execute()
    )

    result: Dict[str, Dict[str, Any]] = {}

    for row in response.data or []:
        candidate_id = row.get("candidate_id")
        state_json = row.get("state_json")

        if candidate_id and isinstance(state_json, dict):
            result[candidate_id] = state_json

    return result


def get_materials_for_candidates(
    candidate_ids: list[str],
) -> Dict[str, list[Dict[str, Any]]]:
    """
    Batch-fetch materials for a set of candidate ids, grouped by
    candidate_id. Used by the dashboard to show submitted/not-submitted
    per row without one query per candidate.
    """

    if not candidate_ids:
        return {}

    response = (
        supabase
        .table("candidate_materials")
        .select("*")
        .in_("candidate_id", candidate_ids)
        .order("created_at", desc=False)
        .execute()
    )

    grouped: Dict[str, list[Dict[str, Any]]] = {}

    for row in response.data or []:
        grouped.setdefault(row["candidate_id"], []).append(row)

    return grouped


# ============================================================================
# INTERVIEW
# ============================================================================

def create_interview(
    candidate_id: str,
) -> Dict[str, Any]:

    data = {
        "candidate_id": candidate_id,
    }

    response = (
        supabase
        .table("interviews")
        .insert(data)
        .execute()
    )

    if not response.data:
        raise RuntimeError(
            "Supabase did not return interview data."
        )

    return response.data[0]


def update_interview(
    interview_id: str,
    updates: Dict[str, Any],
) -> Dict[str, Any]:

    response = (
        supabase
        .table("interviews")
        .update(updates)
        .eq("id", interview_id)
        .execute()
    )

    if not response.data:
        raise RuntimeError(
            "Supabase did not return updated interview data."
        )

    return response.data[0]


def get_active_interview(
    candidate_id: str,
) -> Optional[Dict[str, Any]]:

    response = (
        supabase
        .table("interviews")
        .select("*")
        .eq("candidate_id", candidate_id)
        .eq("status", "active")
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )

    if not response.data:
        return None

    return response.data[0]

# ============================================================================
# INTERVIEW MESSAGE
# ============================================================================

def save_interview_message(
    interview_id: str,
    sender: str,
    message_text: str,
    message_type: str = "text",
    stage: int = 0,
    telegram_message_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:

    data = {
        "interview_id": interview_id,
        "sender": sender,
        "message_text": message_text,
        "message_type": message_type,
        "stage": stage,
        "telegram_message_id": telegram_message_id,
        "metadata": metadata or {},
    }

    response = (
        supabase
        .table("interview_messages")
        .insert(data)
        .execute()
    )

    if not response.data:
        raise RuntimeError(
            "Supabase did not return interview message data."
        )

    return response.data[0]


def get_interview_messages(
    interview_id: str,
) -> list[Dict[str, Any]]:

    response = (
        supabase
        .table("interview_messages")
        .select("*")
        .eq("interview_id", interview_id)
        .order("created_at", desc=False)
        .execute()
    )

    return response.data or []


# ============================================================================
# INTERVIEW SCORE
# ============================================================================

def save_interview_score(
    candidate_id: str,
    interview_id: str,
    total_score: int,
    hunger_score: int,
    skill_score: int,
    engagement_score: int,
    consistency_score: int,
    stability_score: int,
    deductions_total: int,
    score_band: str,
    score_note: Optional[str] = None,
    score_rationale: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:

    data = {
        "candidate_id": candidate_id,
        "interview_id": interview_id,
        "total_score": total_score,
        "hunger_score": hunger_score,
        "skill_score": skill_score,
        "engagement_score": engagement_score,
        "consistency_score": consistency_score,
        "stability_score": stability_score,
        "deductions_total": deductions_total,
        "score_band": score_band,
        "score_note": score_note,
        "score_rationale": score_rationale or {},
    }

    response = (
        supabase
        .table("interview_scores")
        .upsert(
            data,
            on_conflict="interview_id",
        )
        .execute()
    )

    if not response.data:
        raise RuntimeError(
            "Supabase did not return interview score data."
        )

    return response.data[0]


# ============================================================================
# AGENT SESSION (TELEGRAM STATE PERSISTENCE)
# ============================================================================
#
# run_agent() in app/agents/graph.py expects the full AgentState from the
# previous turn. Telegram webhook calls are stateless HTTP requests, so the
# complete state has to be persisted between messages. agent_sessions stores
# that state keyed by Telegram chat ID, plus the last processed Telegram message
# id for idempotency.
# ============================================================================

def get_agent_session(
    phone_number: str,
) -> Optional[Dict[str, Any]]:

    response = (
        supabase
        .table("agent_sessions")
        .select("*")
        .eq("telegram_chat_id", phone_number)
        .limit(1)
        .execute()
    )

    if not response.data:
        return None

    return response.data[0]


def save_agent_session(
    phone_number: str,
    state: Dict[str, Any],
    message_id: Optional[str] = None,
) -> Dict[str, Any]:

    data: Dict[str, Any] = {
        "telegram_chat_id": phone_number,
        "candidate_id": state.get("candidate_id"),
        "interview_id": state.get("interview_id"),
        "state_json": state,
    }

    if message_id:
        data["last_telegram_message_id"] = message_id

    response = (
        supabase
        .table("agent_sessions")
        .upsert(
            data,
            on_conflict="telegram_chat_id",
        )
        .execute()
    )

    if not response.data:
        raise RuntimeError(
            "Supabase did not return agent session data."
        )

    return response.data[0]


def has_processed_message(
    message_id: str,
) -> bool:

    if not message_id:
        return False

    response = (
        supabase
        .table("agent_sessions")
        .select("last_telegram_message_id")
        .eq("last_telegram_message_id", message_id)
        .limit(1)
        .execute()
    )

    return bool(response.data)


# ============================================================================
# OWNER DASHBOARD
# ============================================================================

def get_passed_candidates() -> list[Dict[str, Any]]:
    """Return candidates in the strong (80+) screening band."""

    candidates_response = (
        supabase
        .table("candidates")
        .select("*")
        .eq("status", "completed")
        .execute()
    )

    scores_response = (
        supabase
        .table("interview_scores")
        .select("*")
        .gte("total_score", 80)
        .order("total_score", desc=True)
        .execute()
    )

    candidates_by_id = {
        candidate["id"]: candidate
        for candidate in (candidates_response.data or [])
        if candidate.get("id")
    }

    passed: list[Dict[str, Any]] = []

    for score in scores_response.data or []:
        candidate = candidates_by_id.get(score.get("candidate_id"))
        if candidate:
            passed.append({**candidate, **score})

    return passed