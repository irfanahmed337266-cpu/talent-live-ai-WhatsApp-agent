"""
Talent Live AI Agent - State

Central LangGraph state definition for the separate
Talent Live AI WhatsApp Agent.

IMPORTANT:
- This project is separate from the old Talent Hunt live chat.
- Keep all persistent conversation/interview data here.
- Every field used by graph.py and interview.py should be represented
  in AgentState so LangGraph does not silently drop it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from typing_extensions import TypedDict


# ============================================================================
# CANDIDATE STATE
# ============================================================================

class CandidateState(TypedDict, total=False):
    """
    Candidate information collected during the conversation.
    """

    name: Optional[str]
    phone_number: Optional[str]
    age: Optional[int]
    location: Optional[str]

    experience: Optional[str]
    current_job: Optional[str]

    skills: List[str]
    work_history: List[str]

    education: Optional[str]

    father_occupation: Optional[str]
    brothers: Optional[Any]

    living_situation: Optional[str]
    housing_status: Optional[str]

    background: Optional[str]
    additional_information: Optional[str]


# ============================================================================
# MATERIALS STATE
# ============================================================================

class MaterialsState(TypedDict, total=False):
    """
    Candidate-provided materials.

    Examples:
        CV
        GitHub
        portfolio
        certificates
        recommendations
        other files/materials
    """

    cv: List[Any]
    github: List[Any]
    portfolio: List[Any]
    certificates: List[Any]
    recommendations: List[Any]
    other: List[Any]


# ============================================================================
# INTERVIEW STATE
# ============================================================================

class InterviewState(TypedDict, total=False):
    """
    Deep interview state.

    The interview engine stores:
        - current category
        - questions
        - answers
        - evidence
        - probing information
        - completion state
    """

    current_category: Optional[str]

    questions_asked: List[str]
    answers: List[Any]

    skills_evidence: List[Any]
    work_evidence: List[Any]
    education_evidence: List[Any]
    family_evidence: List[Any]
    open_talk_evidence: List[Any]

    vague_answer_probed: bool
    vague_probe_categories: List[str]

    interview_complete: bool


# ============================================================================
# SCORE STATE
# ============================================================================

class ScoreState(TypedDict, total=False):
    """
    Final candidate scoring state.
    """

    hunger: int
    skill_ability: int
    engagement: int
    consistency_honesty: int
    stability: int

    base_score: int

    dishonesty_minor: int
    dishonesty_major: int
    careless_disrespectful: int
    early_salary_question: int
    repeated_disengagement: int

    total_deductions: int

    final_score: int

    score_band: Optional[str]
    rationale: Optional[str]


# ============================================================================
# CONVERSATION MESSAGE
# ============================================================================

class ConversationMessage(TypedDict, total=False):
    """
    One conversation message.

    Example:
        {
            "role": "user",
            "content": "My name is Ali"
        }
    """

    role: str
    content: str


# ============================================================================
# MAIN AGENT STATE
# ============================================================================

class AgentState(TypedDict, total=False):
    """
    Complete LangGraph state for Talent Live AI Agent.
    """

    # ------------------------------------------------------------------------
    # SESSION
    # ------------------------------------------------------------------------

    session_id: str
    candidate_id: Optional[str]
    interview_id: Optional[str]
    phone_number: str

    created_at: Optional[str]
    updated_at: Optional[str]

    # ------------------------------------------------------------------------
    # CURRENT MESSAGE
    # ------------------------------------------------------------------------

    message: str
    last_user_message: str
    last_ai_message: str

    # ------------------------------------------------------------------------
    # CONVERSATION
    # ------------------------------------------------------------------------

    conversation_history: List[ConversationMessage]

    # ------------------------------------------------------------------------
    # LANGUAGE
    # ------------------------------------------------------------------------

    language: str
    language_locked: bool

    # ------------------------------------------------------------------------
    # STAGE MANAGEMENT
    # ------------------------------------------------------------------------

    stage: int
    previous_stage: Optional[int]
    stage_changed: bool

    # ------------------------------------------------------------------------
    # CANDIDATE
    # ------------------------------------------------------------------------

    candidate: CandidateState

    # ------------------------------------------------------------------------
    # MATERIALS
    # ------------------------------------------------------------------------

    materials: MaterialsState

    materials_received: bool
    materials_skipped: bool

    # IMPORTANT:
    # These two fields are explicitly part of AgentState because graph.py
    # uses them to make Stage 2 persistent across LangGraph invocations.
    materials_prompt_sent: bool
    materials_response_type: Optional[str]

    # ------------------------------------------------------------------------
    # INTERVIEW
    # ------------------------------------------------------------------------

    interview: InterviewState

    # Top-level interview flags are intentionally kept because graph.py
    # directly reads/writes them.
    interview_started: bool
    interview_complete: bool

    # ------------------------------------------------------------------------
    # SCORE
    # ------------------------------------------------------------------------

    score: ScoreState
    scoring_complete: bool
    scoring_completed: bool
    scoring_record: dict
    supabase_score_id: Optional[str]

    total_score: Optional[int]
    hunger_score: Optional[int]
    skill_score: Optional[int]
    engagement_score: Optional[int]
    consistency_score: Optional[int]
    stability_score: Optional[int]
    deductions_total: Optional[int]
    score_band: Optional[str]
    score_note: Optional[str]
    score_rationale: object

    # ------------------------------------------------------------------------
    # AGENT FLAGS
    # ------------------------------------------------------------------------

    greeting_sent: bool
    ai_disclosure_sent: bool
    model_explanation_sent: bool

    logged: bool
    candidate_responded: bool

    should_continue: bool
    should_end: bool

    # ------------------------------------------------------------------------
    # RESPONSE
    # ------------------------------------------------------------------------

    ai_response: str
    model_explanation: Optional[str]
    next_question: Optional[str]

    # ------------------------------------------------------------------------
    # INTERNAL NOTES / ERRORS
    # ------------------------------------------------------------------------

    system_notes: List[str]
    errors: List[str]


# ============================================================================
# DEFAULT FACTORIES
# ============================================================================

def create_initial_candidate(
    phone_number: Optional[str] = None,
) -> CandidateState:
    """
    Create an empty candidate object.
    """

    return {
        "name": None,
        "phone_number": phone_number,

        "age": None,
        "location": None,

        "experience": None,
        "current_job": None,

        "skills": [],
        "work_history": [],

        "education": None,

        "father_occupation": None,
        "brothers": None,

        "living_situation": None,
        "housing_status": None,

        "background": None,
        "additional_information": None,
    }


def create_initial_materials() -> MaterialsState:
    """
    Create an empty materials state.
    """

    return {
        "cv": [],
        "github": [],
        "portfolio": [],
        "certificates": [],
        "recommendations": [],
        "other": [],
    }


def create_initial_interview() -> InterviewState:
    """
    Create an empty interview state.
    """

    return {
        "current_category": None,

        "questions_asked": [],
        "answers": [],

        "skills_evidence": [],
        "work_evidence": [],
        "education_evidence": [],
        "family_evidence": [],
        "open_talk_evidence": [],

        "vague_answer_probed": False,
        "vague_probe_categories": [],

        "interview_complete": False,
    }


def create_initial_score() -> ScoreState:
    """
    Create an empty score state.
    """

    return {
        "hunger": 0,
        "skill_ability": 0,
        "engagement": 0,
        "consistency_honesty": 0,
        "stability": 0,

        "base_score": 0,

        "dishonesty_minor": 0,
        "dishonesty_major": 0,
        "careless_disrespectful": 0,
        "early_salary_question": 0,
        "repeated_disengagement": 0,

        "total_deductions": 0,

        "final_score": 0,

        "score_band": None,
        "rationale": None,
    }


# ============================================================================
# INITIAL STATE
# ============================================================================

def create_initial_state(
    candidate_id: Optional[str] = None,
    phone_number: str = "",
    session_id: str = "talent-live-session",
) -> AgentState:
    """
    Create a completely initialized Talent Live agent state.

    This function is used when a new WhatsApp conversation starts.
    """

    now = datetime.utcnow().isoformat()

    state: AgentState = {
        # --------------------------------------------------------------------
        # SESSION
        # --------------------------------------------------------------------

        "session_id": session_id,

        "candidate_id": candidate_id,
        "interview_id": None,
        
        "phone_number": phone_number,

        "created_at": now,
        "updated_at": now,

        # --------------------------------------------------------------------
        # CURRENT MESSAGE
        # --------------------------------------------------------------------

        "message": "",
        "last_user_message": "",
        "last_ai_message": "",

        # --------------------------------------------------------------------
        # CONVERSATION
        # --------------------------------------------------------------------

        "conversation_history": [],

        # --------------------------------------------------------------------
        # LANGUAGE
        # --------------------------------------------------------------------

        "language": "urdu",
        "language_locked": False,

        # --------------------------------------------------------------------
        # STAGE
        # --------------------------------------------------------------------
        #
        # 0 = Initial
        # 1 = Basic information
        # 2 = Materials / open invitation
        # 3 = Deep interview
        # 4 = Model explanation
        # 5 = Scoring / logging
        #

        "stage": 0,
        "previous_stage": None,
        "stage_changed": False,

        # --------------------------------------------------------------------
        # CANDIDATE
        # --------------------------------------------------------------------

        "candidate": create_initial_candidate(
            phone_number=phone_number
        ),

        # --------------------------------------------------------------------
        # MATERIALS
        # --------------------------------------------------------------------

        "materials": create_initial_materials(),

        "materials_received": False,
        "materials_skipped": False,

        # IMPORTANT STAGE-2 PERSISTENCE FIELDS
        "materials_prompt_sent": False,
        "materials_response_type": None,

        # --------------------------------------------------------------------
        # INTERVIEW
        # --------------------------------------------------------------------

        "interview": create_initial_interview(),

        "interview_started": False,
        "interview_complete": False,

        # --------------------------------------------------------------------
        # SCORE
        # --------------------------------------------------------------------

        "score": create_initial_score(),

        "scoring_complete": False,

        # --------------------------------------------------------------------
        # AGENT FLAGS
        # --------------------------------------------------------------------

        "greeting_sent": False,
        "ai_disclosure_sent": False,
        "model_explanation_sent": False,

        "logged": False,

        "candidate_responded": False,

        "should_continue": True,
        "should_end": False,

        # --------------------------------------------------------------------
        # RESPONSE
        # --------------------------------------------------------------------

        "ai_response": "",
        "model_explanation": None,
        "next_question": None,

        # --------------------------------------------------------------------
        # NOTES
        # --------------------------------------------------------------------

        "system_notes": [],
        "errors": [],
    }

    return state


# ============================================================================
# STATE UPDATE HELPER
# ============================================================================

def update_state_timestamp(
    state: AgentState,
) -> AgentState:
    """
    Update the state's updated_at timestamp.
    """

    state["updated_at"] = datetime.utcnow().isoformat()

    return state


# ============================================================================
# SAFE STATE COPY
# ============================================================================

def clone_state(
    state: AgentState,
) -> AgentState:
    """
    Return a deep copy of the current state.

    Useful when manipulating state outside LangGraph.
    """

    from copy import deepcopy

    return deepcopy(state)


# ============================================================================
# STATE DEBUG HELPER
# ============================================================================

def summarize_state(
    state: AgentState,
) -> Dict[str, Any]:
    """
    Return a small state summary for debugging/logging.
    """

    candidate = (
        state.get("candidate", {})
        or {}
    )

    interview = (
        state.get("interview", {})
        or {}
    )

    score = (
        state.get("score", {})
        or {}
    )

    return {
        "session_id": state.get(
            "session_id"
        ),

        "candidate_id": state.get(
            "candidate_id"
        ),

        "phone_number": state.get(
            "phone_number"
        ),

        "stage": state.get(
            "stage"
        ),

        "language": state.get(
            "language"
        ),

        "candidate_name": candidate.get(
            "name"
        ),

        "candidate_age": candidate.get(
            "age"
        ),

        "candidate_location": candidate.get(
            "location"
        ),

        "candidate_experience": candidate.get(
            "experience"
        ),

        "materials_prompt_sent": state.get(
            "materials_prompt_sent"
        ),

        "materials_response_type": state.get(
            "materials_response_type"
        ),

        "materials_received": state.get(
            "materials_received"
        ),

        "materials_skipped": state.get(
            "materials_skipped"
        ),

        "interview_started": state.get(
            "interview_started"
        ),

        "interview_complete": state.get(
            "interview_complete"
        ),

        "current_interview_category": interview.get(
            "current_category"
        ),

        "questions_asked": len(
            interview.get(
                "questions_asked",
                [],
            )
            or []
        ),

        "answers": len(
            interview.get(
                "answers",
                [],
            )
            or []
        ),

        "scoring_complete": state.get(
            "scoring_complete"
        ),

        "final_score": score.get(
            "final_score"
        ),

        "conversation_messages": len(
            state.get(
                "conversation_history",
                [],
            )
            or []
        ),

        "ai_response": state.get(
            "ai_response"
        ),

        "next_question": state.get(
            "next_question"
        ),
    }


# ============================================================================
# MODULE TEST
# ============================================================================

if __name__ == "__main__":

    print("=" * 78)
    print("TALENT LIVE - STATE TEST")
    print("=" * 78)

    test_state = create_initial_state(
        candidate_id="test-001",
        phone_number="+923000000000",
    )

    print()
    print("STATE IMPORT OK")

    print()
    print("Initial State:")

    import json

    print(
        json.dumps(
            test_state,
            indent=2,
            ensure_ascii=False,
        )
    )

    print()
    print("State Summary:")

    print(
        json.dumps(
            summarize_state(
                test_state
            ),
            indent=2,
            ensure_ascii=False,
        )
    )

    print()
    print("=" * 78)
    print("STATE TEST COMPLETE")
    print("=" * 78)