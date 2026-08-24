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
        "whatsapp_number": phone_number,
        **candidate,
    }

    response = (
        supabase
        .table("candidates")
        .upsert(
            data,
            on_conflict="whatsapp_number",
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
        .eq("whatsapp_number", phone_number)
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
    whatsapp_message_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:

    data = {
        "interview_id": interview_id,
        "sender": sender,
        "message_text": message_text,
        "message_type": message_type,
        "stage": stage,
        "whatsapp_message_id": whatsapp_message_id,
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