"""
Talent Live AI Agent - Stage 5 Scoring Engine

Deterministic scoring engine for the completed interview.

The engine:
- Reads candidate/interview evidence.
- Calculates the five Talent Live score categories.
- Applies deductions.
- Produces a final 1-100 score.
- Produces a score band and rationale.

IMPORTANT:
Do not invent candidate facts here.
The scoring engine only scores evidence that already exists
in the candidate/interview state.
"""

from __future__ import annotations

from typing import Any, Dict, List


# ============================================================================
# SCORE LIMITS
# ============================================================================

HUNGER_MAX = 40
SKILL_MAX = 25
ENGAGEMENT_MAX = 15
CONSISTENCY_MAX = 15
STABILITY_MAX = 5

BASE_SCORE_MAX = 100


# ============================================================================
# DEDUCTIONS
# ============================================================================

DISHONESTY_MINOR_DEDUCTION = 20
DISHONESTY_MAJOR_DEDUCTION = 40
CARELESS_DISRESPECTFUL_DEDUCTION = 25
EARLY_SALARY_DEDUCTION = 10
REPEATED_DISENGAGEMENT_DEDUCTION = 10


# ============================================================================
# HELPERS
# ============================================================================

def _safe_list(value: Any) -> List[Any]:
    """Return value as a list, otherwise an empty list."""

    if isinstance(value, list):
        return value

    if value is None:
        return []

    return [value]


def _text(value: Any) -> str:
    """Safely convert a value to searchable text."""

    if value is None:
        return ""

    if isinstance(value, str):
        return value.strip()

    return str(value).strip()


def _combined_text(state: Dict[str, Any]) -> str:
    """
    Combine available candidate/interview evidence into searchable text.
    """

    candidate = state.get("candidate", {}) or {}
    interview = state.get("interview", {}) or {}

    parts: List[str] = []

    for value in candidate.values():
        if isinstance(value, list):
            parts.extend(_text(item) for item in value)
        else:
            text = _text(value)

            if text:
                parts.append(text)

    for key in (
        "questions_asked",
        "answers",
        "skills_evidence",
        "work_evidence",
        "education_evidence",
        "family_evidence",
        "open_talk_evidence",
    ):
        for value in _safe_list(interview.get(key)):
            if isinstance(value, dict):
                parts.extend(
                    _text(item)
                    for item in value.values()
                )
            else:
                parts.append(_text(value))

    return " ".join(
        part
        for part in parts
        if part
    )


def _count_answers(state: Dict[str, Any]) -> int:
    interview = state.get("interview", {}) or {}

    answers = interview.get(
        "answers",
        [],
    )

    return len(
        answers
        if isinstance(answers, list)
        else []
    )


def _count_questions(state: Dict[str, Any]) -> int:
    interview = state.get("interview", {}) or {}

    questions = interview.get(
        "questions_asked",
        [],
    )

    return len(
        questions
        if isinstance(questions, list)
        else []
    )


# ============================================================================
# HUNGER / WILLINGNESS
# ============================================================================

def calculate_hunger_score(
    state: Dict[str, Any],
) -> int:
    """
    Score willingness, motivation and desire to work.

    Maximum: 40
    """

    candidate = state.get(
        "candidate",
        {},
    ) or {}

    interview = state.get(
        "interview",
        {},
    ) or {}

    score = 0

    # Work experience indicates willingness to participate in work.
    if candidate.get("experience"):
        score += 8

    if candidate.get("current_job"):
        score += 4

    # Motivation/open-talk evidence.
    open_talk = _safe_list(
        interview.get(
            "open_talk_evidence",
            [],
        )
    )

    if open_talk:
        score += 8

    # Work evidence.
    work_evidence = _safe_list(
        interview.get(
            "work_evidence",
            [],
        )
    )

    if work_evidence:
        score += 8

    # Skill evidence often demonstrates practical willingness.
    skills_evidence = _safe_list(
        interview.get(
            "skills_evidence",
            [],
        )
    )

    if skills_evidence:
        score += 6

    # Completed interview demonstrates persistence.
    if state.get("interview_complete") is True:
        score += 6

    return min(
        score,
        HUNGER_MAX,
    )


# ============================================================================
# SKILL / ABILITY
# ============================================================================

def calculate_skill_score(
    state: Dict[str, Any],
) -> int:
    """
    Score demonstrated skills and ability.

    Maximum: 25
    """

    candidate = state.get(
        "candidate",
        {},
    ) or {}

    interview = state.get(
        "interview",
        {},
    ) or {}

    score = 0

    skills = _safe_list(
        candidate.get(
            "skills",
            [],
        )
    )

    work_history = _safe_list(
        candidate.get(
            "work_history",
            [],
        )
    )

    skills_evidence = _safe_list(
        interview.get(
            "skills_evidence",
            [],
        )
    )

    work_evidence = _safe_list(
        interview.get(
            "work_evidence",
            [],
        )
    )

    # Explicitly listed skills.
    if skills:
        score += min(
            len(skills) * 3,
            9,
        )

    # Work history.
    if work_history:
        score += min(
            len(work_history) * 2,
            4,
        )

    # Interview evidence.
    if skills_evidence:
        score += 6

    if work_evidence:
        score += 6

    return min(
        score,
        SKILL_MAX,
    )


# ============================================================================
# ENGAGEMENT
# ============================================================================

def calculate_engagement_score(
    state: Dict[str, Any],
) -> int:
    """
    Score participation and responsiveness.

    Maximum: 15
    """

    interview = state.get(
        "interview",
        {},
    ) or {}

    answers = _safe_list(
        interview.get(
            "answers",
            [],
        )
    )

    score = 0

    answer_count = len(answers)

    if answer_count >= 3:
        score += 5

    if answer_count >= 6:
        score += 5

    if state.get("interview_complete") is True:
        score += 5

    return min(
        score,
        ENGAGEMENT_MAX,
    )


# ============================================================================
# CONSISTENCY / HONESTY
# ============================================================================

def calculate_consistency_score(
    state: Dict[str, Any],
) -> int:
    """
    Score consistency and honesty.

    Maximum: 15

    The interview engine's probing flags are used when available.
    """

    interview = state.get(
        "interview",
        {},
    ) or {}

    score = CONSISTENCY_MAX

    vague_probe_count = len(
        _safe_list(
            interview.get(
                "vague_probe_categories",
                [],
            )
        )
    )

    # Probing itself is not dishonesty.
    # Only reduce the score when the state explicitly indicates
    # repeated problematic answers.
    if vague_probe_count >= 3:
        score -= 3

    if interview.get(
        "vague_answer_probed"
    ) is True:
        score -= 1

    return max(
        0,
        min(
            score,
            CONSISTENCY_MAX,
        ),
    )


# ============================================================================
# STABILITY
# ============================================================================

def calculate_stability_score(
    state: Dict[str, Any],
) -> int:
    """
    Score available stability information.

    Maximum: 5
    """

    candidate = state.get(
        "candidate",
        {},
    ) or {}

    score = 0

    if candidate.get("current_job"):
        score += 2

    if candidate.get("living_situation"):
        score += 1

    if candidate.get("housing_status"):
        score += 1

    if candidate.get("education"):
        score += 1

    return min(
        score,
        STABILITY_MAX,
    )


# ============================================================================
# DEDUCTIONS
# ============================================================================

def calculate_deductions(
    state: Dict[str, Any],
) -> Dict[str, int]:
    """
    Calculate explicit deductions.

    IMPORTANT:
    We do not infer serious misconduct from ordinary answers.
    Deductions should only be applied when evidence is explicit.
    """

    interview = state.get(
        "interview",
        {},
    ) or {}

    deductions = {
        "dishonesty_minor": 0,
        "dishonesty_major": 0,
        "careless_disrespectful": 0,
        "early_salary_question": 0,
        "repeated_disengagement": 0,
    }

    # These flags may be added later by the interview/scoring
    # analysis layer. For now we safely read only explicit state.
    if state.get(
        "dishonesty_minor"
    ) is True:
        deductions["dishonesty_minor"] = (
            DISHONESTY_MINOR_DEDUCTION
        )

    if state.get(
        "dishonesty_major"
    ) is True:
        deductions["dishonesty_major"] = (
            DISHONESTY_MAJOR_DEDUCTION
        )

    if state.get(
        "careless_disrespectful"
    ) is True:
        deductions["careless_disrespectful"] = (
            CARELESS_DISRESPECTFUL_DEDUCTION
        )

    if state.get(
        "early_salary_question"
    ) is True:
        deductions["early_salary_question"] = (
            EARLY_SALARY_DEDUCTION
        )

    if state.get(
        "repeated_disengagement"
    ) is True:
        deductions["repeated_disengagement"] = (
            REPEATED_DISENGAGEMENT_DEDUCTION
        )

    return deductions


# ============================================================================
# SCORE BAND
# ============================================================================

def get_score_band(
    score: int,
) -> str:
    """Convert final score into a Talent Live score band."""

    if score >= 80:
        return "strong"

    if score >= 50:
        return "borderline"

    return "weak"


# ============================================================================
# RATIONALE
# ============================================================================

def build_score_rationale(
    hunger: int,
    skill: int,
    engagement: int,
    consistency: int,
    stability: int,
    deductions: Dict[str, int],
    final_score: int,
) -> str:
    """Create a concise explanation of the calculated score."""

    strongest = max(
        (
            ("hunger", hunger),
            ("skill", skill),
            ("engagement", engagement),
            ("consistency", consistency),
            ("stability", stability),
        ),
        key=lambda item: item[1],
    )

    total_deductions = sum(
        deductions.values()
    )

    if total_deductions:
        return (
            f"Final score {final_score}/100. "
            f"Strongest area: {strongest[0]} "
            f"({strongest[1]} points). "
            f"Total deductions: {total_deductions}."
        )

    return (
        f"Final score {final_score}/100. "
        f"Strongest area: {strongest[0]} "
        f"({strongest[1]} points). "
        "No explicit deductions were applied."
    )


# ============================================================================
# MAIN SCORING ENGINE
# ============================================================================

def calculate_score(
    state: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Calculate the complete Stage 5 score.

    Returns fields compatible with graph.py.
    """

    hunger_score = calculate_hunger_score(
        state
    )

    skill_score = calculate_skill_score(
        state
    )

    engagement_score = calculate_engagement_score(
        state
    )

    consistency_score = calculate_consistency_score(
        state
    )

    stability_score = calculate_stability_score(
        state
    )

    base_score = (
        hunger_score
        + skill_score
        + engagement_score
        + consistency_score
        + stability_score
    )

    deductions = calculate_deductions(
        state
    )

    deductions_total = sum(
        deductions.values()
    )

    total_score = max(
        1,
        min(
            BASE_SCORE_MAX,
            base_score - deductions_total,
        ),
    )

    score_band = get_score_band(
        total_score
    )

    score_rationale = build_score_rationale(
        hunger=hunger_score,
        skill=skill_score,
        engagement=engagement_score,
        consistency=consistency_score,
        stability=stability_score,
        deductions=deductions,
        final_score=total_score,
    )

    score_note = (
        f"Talent Live assessment score: "
        f"{total_score}/100 ({score_band})."
    )

    return {
        # Fields expected by graph.py
        "total_score": total_score,
        "hunger_score": hunger_score,
        "skill_score": skill_score,
        "engagement_score": engagement_score,
        "consistency_score": consistency_score,
        "stability_score": stability_score,
        "deductions_total": deductions_total,
        "score_band": score_band,
        "score_note": score_note,
        "score_rationale": score_rationale,

        # Detailed score structure
        "score": {
            "hunger": hunger_score,
            "skill_ability": skill_score,
            "engagement": engagement_score,
            "consistency_honesty": consistency_score,
            "stability": stability_score,
            "base_score": base_score,

            "dishonesty_minor": deductions[
                "dishonesty_minor"
            ],
            "dishonesty_major": deductions[
                "dishonesty_major"
            ],
            "careless_disrespectful": deductions[
                "careless_disrespectful"
            ],
            "early_salary_question": deductions[
                "early_salary_question"
            ],
            "repeated_disengagement": deductions[
                "repeated_disengagement"
            ],

            "total_deductions": deductions_total,
            "final_score": total_score,
            "score_band": score_band,
            "rationale": score_rationale,
        },
    }


# ============================================================================
# STATE APPLIER
# ============================================================================

def apply_score(
    state: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Calculate the score and merge it into AgentState.
    """

    result = calculate_score(
        state
    )

    state["total_score"] = result[
        "total_score"
    ]

    state["hunger_score"] = result[
        "hunger_score"
    ]

    state["skill_score"] = result[
        "skill_score"
    ]

    state["engagement_score"] = result[
        "engagement_score"
    ]

    state["consistency_score"] = result[
        "consistency_score"
    ]

    state["stability_score"] = result[
        "stability_score"
    ]

    state["deductions_total"] = result[
        "deductions_total"
    ]

    state["score_band"] = result[
        "score_band"
    ]

    state["score_note"] = result[
        "score_note"
    ]

    state["score_rationale"] = result[
        "score_rationale"
    ]

    state["score"] = result[
        "score"
    ]

    state["scoring_complete"] = True

    return state


# ============================================================================
# SIMPLE TEST
# ============================================================================

if __name__ == "__main__":

    test_state = {
        "candidate": {
            "experience": "3 years",
            "current_job": "Sales executive",
            "skills": [
                "sales",
                "customer handling",
            ],
            "work_history": [
                "Sales executive",
            ],
            "education": "Bachelor",
            "living_situation": "With family",
            "housing_status": "Own house",
        },

        "interview": {
            "questions_asked": [
                "Tell me about your work.",
                "What skills do you have?",
                "Why do you want to work?",
                "Tell me about your experience.",
                "Tell me about your goals.",
                "Anything else?",
            ],

            "answers": [
                "I worked in sales.",
                "I handle customers.",
                "I want to improve.",
                "I have three years experience.",
                "I want to learn and earn.",
                "I am willing to work.",
            ],

            "skills_evidence": [
                "sales",
                "customer handling",
            ],

            "work_evidence": [
                "sales experience",
            ],

            "education_evidence": [
                "Bachelor",
            ],

            "family_evidence": [
                "lives with family",
            ],

            "open_talk_evidence": [
                "motivated to learn and work",
            ],

            "vague_answer_probed": False,
            "vague_probe_categories": [],
        },

        "interview_complete": True,
    }

    result = calculate_score(
        test_state
    )

    import json

    print("=" * 78)
    print("TALENT LIVE - SCORING ENGINE TEST")
    print("=" * 78)

    print(
        json.dumps(
            result,
            indent=2,
            ensure_ascii=False,
        )
    )

    print("=" * 78)
    print("SCORING TEST COMPLETE")
    print("=" * 78)