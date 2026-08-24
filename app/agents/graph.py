"""
Talent Live - Interview Engine

File:
    app/agents/interview.py

Purpose:
- Implement the Talent Live interview/question flow.
- Keep the existing AgentState structure compatible.
- Handle Stage 2 materials/open invitation.
- Handle Stage 3 deep interview.
- Ask one question at a time.
- Track every asked question.
- Track every candidate answer.
- Associate answers with their exact interview question/category.
- Avoid repeating questions unnecessarily.
- Probe vague answers at most once per category.
- Support Urdu, Roman Urdu, and English.
- Never ask direct financial questions.
- Keep the interview compatible with graph.py/state.py.

IMPORTANT:
- This module does NOT perform scoring.
- This module does NOT call Gemini.
- This module does NOT access the database.
"""



from __future__ import annotations

import os

try:
    from google import genai
except ImportError:
    genai = None


GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

GEMINI_MODEL = os.getenv(
    "GEMINI_MODEL",
    "gemini-2.5-flash",
)

USE_GEMINI_EXTRACTION = (
    os.getenv(
        "USE_GEMINI_EXTRACTION",
        "false",
    ).lower()
    == "true"
)


gemini_client = None

if genai and GEMINI_API_KEY:

    try:

        gemini_client = genai.Client(
            api_key=GEMINI_API_KEY
        )

    except Exception:

        gemini_client = None

import re

from datetime import datetime, timezone, timedelta
from app.agents.scoring import apply_score
from typing import Any, Dict, List, Optional
from copy import deepcopy

from langgraph.graph import (
    StateGraph,
    START,
    END,
)
from app.agents.state import AgentState
from app.agents.interview import (
    process_answer,
    interview_node,
    generate_next_question,
)

from app.services.supabase import (
    upsert_candidate,
    create_interview,
    update_candidate,
    update_interview,
    save_interview_score,
)

# ============================================================
# CONSTANTS
# ============================================================

STAGE_INITIAL = 0
STAGE_BASIC = 1
STAGE_MATERIALS = 2
STAGE_INTERVIEW = 3
STAGE_MODEL_EXPLANATION = 4
STAGE_SCORING = 5


# ============================================================
# STAGE 2 - MATERIALS / OPEN INVITATION
# ============================================================

MATERIALS_QUESTIONS = {
    "english": (
        "If you've got a CV, GitHub, portfolio, certificates, past work, "
        "or anything else that shows what you can do, send it over — "
        "send as much or as little as you want, nothing's required.\n\n"
        "And beyond that, feel free to just talk. Don't worry about saying "
        "it perfectly or organizing it. Tell me about yourself, your work, "
        "or anything you think is worth knowing."
    ),
    "urdu": (
        "اگر آپ کے پاس CV، GitHub، portfolio، certificates، past work، "
        "یا کوئی اور چیز ہے جو آپ کی skills دکھاتی ہے تو وہ بھیج سکتے ہیں۔ "
        "جتنا یا جتنا کم چاہیں، کچھ بھی لازمی نہیں ہے۔\n\n"
        "اس کے علاوہ آپ اپنے بارے میں، اپنے کام کے بارے میں، یا کسی بھی "
        "ایسی چیز کے بارے میں کھل کر بتا سکتے ہیں جو آپ کے خیال میں "
        "معلوم ہونی چاہیے۔"
    ),
    "roman_urdu": (
        "Agar aap ke paas CV, GitHub, portfolio, certificates, past work "
        "ya koi aur cheez hai jo aapki skills show karti hai to bhej sakte "
        "hain. Jitna ya jitna kam chahein, kuch bhi lazmi nahi hai.\n\n"
        "Is ke ilawa apne bare mein, apne kaam ke bare mein, ya kisi bhi "
        "aisi cheez ke bare mein freely bata sakte hain jo aap ke khayal "
        "mein maloom honi chahiye."
    ),
}


# ============================================================
# STAGE 3 - DEEP INTERVIEW QUESTION BANK
# ============================================================

QUESTION_BANK = {
    "skills": {
        "english": [
            (
                "What are you actually good at? Doesn't have to be coding — "
                "could be sales, marketing, managing people, anything."
            ),
            (
                "Tell me about a specific time you used that skill — what "
                "was the situation, and what did you do?"
            ),
            "Can you walk me through an actual example?",
        ],
        "urdu": [
            (
                "آپ حقیقت میں کس کام میں اچھے ہیں؟ ضروری نہیں coding ہو — "
                "sales، marketing، لوگوں کو manage کرنا، کچھ بھی ہو سکتا ہے۔"
            ),
            (
                "کسی ایسے خاص موقع کے بارے میں بتائیں جب آپ نے یہ skill "
                "استعمال کی۔ صورتحال کیا تھی اور آپ نے کیا کیا؟"
            ),
            "کیا آپ کوئی حقیقی مثال بتا سکتے ہیں اور تھوڑا سمجھا سکتے ہیں؟",
        ],
        "roman_urdu": [
            (
                "Aap asal mein kis kaam mein ache hain? Zaroori nahi coding "
                "ho — sales, marketing, logon ko manage karna, kuch bhi ho "
                "sakta hai."
            ),
            (
                "Kisi aise specific waqt ke bare mein batayein jab aap ne "
                "ye skill use ki. Situation kya thi aur aap ne kya kiya?"
            ),
            (
                "Kya aap koi real example bata sakte hain aur thora explain "
                "kar sakte hain?"
            ),
        ],
    },

    "work": {
        "english": [
            "What are you doing right now for work?",
            "How's that going? What do you actually do day to day there?",
            "What's been your best result or achievement there?",
        ],
        "urdu": [
            "آپ اس وقت کام کے لیے کیا کر رہے ہیں؟",
            "وہ کام کیسا جا رہا ہے؟ آپ روزانہ وہاں اصل میں کیا کرتے ہیں؟",
            "وہاں آپ کا سب سے اچھا result یا achievement کیا رہا ہے؟",
        ],
        "roman_urdu": [
            "Aap is waqt kaam ke liye kya kar rahe hain?",
            (
                "Wo kaam kaisa ja raha hai? Aap rozana wahan asal mein kya "
                "karte hain?"
            ),
            (
                "Wahan aapka sab se acha result ya achievement kya raha hai?"
            ),
        ],
    },

    "education": {
        "english": [
            "What did you study, and where?",
            "Did you finish, or is it still ongoing?",
        ],
        "urdu": [
            "آپ نے کیا پڑھائی کی اور کہاں سے کی؟",
            "آپ کی پڑھائی مکمل ہو گئی ہے یا ابھی جاری ہے؟",
        ],
        "roman_urdu": [
            "Aap ne kya parhai ki aur kahan se ki?",
            "Aapki parhai complete ho gayi hai ya abhi jari hai?",
        ],
    },

    "family": {
        "english": [
            "Tell me a bit about your family — what does your father do?",
            "Do you have brothers? What do they do?",
            "Do you all live together, or on your own?",
            "Is where you live your own place, or rented?",
        ],
        "urdu": [
            "اپنی family کے بارے میں تھوڑا بتائیں — آپ کے والد کیا کرتے ہیں؟",
            "کیا آپ کے بھائی ہیں؟ وہ کیا کرتے ہیں؟",
            "کیا آپ سب ایک ساتھ رہتے ہیں یا آپ الگ رہتے ہیں؟",
            "جہاں آپ رہتے ہیں وہ اپنا گھر ہے یا کرائے کا؟",
        ],
        "roman_urdu": [
            (
                "Apni family ke bare mein thora batayein — aapke father "
                "kya karte hain?"
            ),
            "Kya aapke brothers hain? Wo kya karte hain?",
            "Kya aap sab ek sath rehte hain ya aap alag rehte hain?",
            "Jahan aap rehte hain wo apna ghar hai ya rent par hai?",
        ],
    },

    "open_talk": {
        "english": [
            (
                "Anything else about yourself you think is worth me "
                "knowing? Just talk, I'll catch what matters."
            ),
        ],
        "urdu": [
            (
                "اپنے بارے میں کوئی اور ایسی بات جو آپ سمجھتے ہیں کہ مجھے "
                "معلوم ہونی چاہیے؟ بس کھل کر بتائیں، جو ضروری ہوگا میں سمجھ لوں گا۔"
            ),
        ],
        "roman_urdu": [
            (
                "Apne bare mein koi aur aisi baat jo aap samajhte hain ke "
                "mujhe maloom honi chahiye? Bas freely batayein, jo zaroori "
                "hoga main samajh lunga."
            ),
        ],
    },
}


# ============================================================
# QUESTION FIELD MAPPING
# ============================================================

CATEGORY_REQUIRED_FIELDS = {
    "skills": [
        "skills",
    ],
    "work": [
        "current_job",
        "work_history",
    ],
    "education": [
        "education",
    ],
    "family": [
        "father_occupation",
        "brothers",
        "living_situation",
        "housing_status",
    ],
    "open_talk": [
        "additional_information",
    ],
}


CATEGORY_ORDER = [
    "skills",
    "work",
    "education",
    "family",
    "open_talk",
]


# ============================================================
# LANGUAGE HELPERS
# ============================================================

def normalize_language(
    language: Optional[str],
) -> str:

    if not language:
        return "urdu"

    value = str(language).strip().lower()

    aliases = {
        "en": "english",
        "eng": "english",
        "english": "english",

        "ur": "urdu",
        "urdu": "urdu",

        "roman": "roman_urdu",
        "roman urdu": "roman_urdu",
        "roman-urdu": "roman_urdu",
        "roman_urdu": "roman_urdu",
    }

    return aliases.get(value, "urdu")


def get_question_language(
    state: Dict[str, Any],
) -> str:

    return normalize_language(
        state.get("language")
    )


# ============================================================
# SAFE STATE HELPERS
# ============================================================

def get_candidate(
    state: Dict[str, Any],
) -> Dict[str, Any]:

    candidate = state.get("candidate")

    if not isinstance(candidate, dict):
        return {}

    return candidate


def get_interview(
    state: Dict[str, Any],
) -> Dict[str, Any]:

    interview = state.get("interview")

    if not isinstance(interview, dict):
        return {}

    return interview


def ensure_interview_structure(
    state: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Ensure the interview section contains all expected fields.

    pending_question + pending_category are the authoritative
    context for the candidate's next answer.
    """

    interview = state.get("interview")

    if not isinstance(interview, dict):
        interview = {}

    if not isinstance(
        interview.get("questions_asked"),
        list,
    ):
        interview["questions_asked"] = []

    if not isinstance(
        interview.get("answers"),
        list,
    ):
        interview["answers"] = []

    interview.setdefault(
        "current_category",
        None,
    )

    interview.setdefault(
        "current_question",
        None,
    )

    # --------------------------------------------------------
    # AUTHORITATIVE PENDING QUESTION CONTEXT
    # --------------------------------------------------------

    interview.setdefault(
        "pending_category",
        None,
    )

    interview.setdefault(
        "pending_question",
        None,
    )

    interview.setdefault(
        "skills_evidence",
        [],
    )

    interview.setdefault(
        "work_evidence",
        [],
    )

    interview.setdefault(
        "education_evidence",
        [],
    )

    interview.setdefault(
        "family_evidence",
        [],
    )

    interview.setdefault(
        "open_talk_evidence",
        [],
    )

    interview.setdefault(
        "vague_answer_probed",
        False,
    )

    interview.setdefault(
        "vague_probe_categories",
        [],
    )

    interview.setdefault(
        "interview_complete",
        False,
    )

    state["interview"] = interview

    return state


# ============================================================
# VALUE CHECKING
# ============================================================

def is_populated(
    value: Any,
) -> bool:

    if value is None:
        return False

    if isinstance(value, str):
        return bool(value.strip())

    if isinstance(value, list):
        return len(value) > 0

    if isinstance(value, dict):
        return len(value) > 0

    return True


def category_has_information(
    category: str,
    candidate: Dict[str, Any],
) -> bool:

    fields = CATEGORY_REQUIRED_FIELDS.get(
        category,
        [],
    )

    for field in fields:

        if is_populated(
            candidate.get(field)
        ):
            return True

    return False


# ============================================================
# VAGUE ANSWER DETECTION
# ============================================================

def is_vague_answer(
    answer: str,
) -> bool:

    if answer is None:
        return True

    text = str(answer).strip().lower()

    if not text:
        return True

    vague_answers = {
        "yes",
        "no",
        "haan",
        "han",
        "ji",
        "nahi",
        "nahin",
        "theek",
        "okay",
        "ok",
        "bas",
        "nothing",
        "kuch nahi",
        "pata nahi",
        "don't know",
        "dont know",
        "idk",
        "yes sir",
        "haan ji",
        "ji sir",
        "no sir",
        "nahi sir",
    }

    if text in vague_answers:
        return True

    words = text.split()

    if len(words) <= 2:
        return True

    return False


# ============================================================
# QUESTION TRACKING
# ============================================================

def get_questions_asked(
    state: Dict[str, Any],
) -> List[str]:

    interview = get_interview(state)

    questions = interview.get(
        "questions_asked",
        [],
    )

    if not isinstance(questions, list):
        return []

    return questions


def normalize_question(
    question: str,
) -> str:

    return " ".join(
        str(question)
        .strip()
        .lower()
        .split()
    )


def question_already_asked(
    state: Dict[str, Any],
    question: str,
) -> bool:

    if not question:
        return False

    normalized = normalize_question(
        question
    )

    for asked in get_questions_asked(state):

        if not isinstance(
            asked,
            str,
        ):
            continue

        if normalize_question(
            asked
        ) == normalized:
            return True

    return False


# ============================================================
# RECORD QUESTION
# ============================================================

def record_question(
    state: Dict[str, Any],
    question: str,
    category: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Record a newly generated question.

    IMPORTANT:
    pending_question + pending_category represent the exact
    question/category that the next candidate answer belongs to.
    """

    ensure_interview_structure(state)

    if not question:
        return state

    interview = state["interview"]

    if category is None:
        category = interview.get(
            "current_category"
        )

    questions = interview.setdefault(
        "questions_asked",
        [],
    )

    if not question_already_asked(
        state,
        question,
    ):
        questions.append(question)

    # --------------------------------------------------------
    # Current display state
    # --------------------------------------------------------

    interview["current_category"] = category
    interview["current_question"] = question

    # --------------------------------------------------------
    # AUTHORITATIVE ANSWER CONTEXT
    # --------------------------------------------------------

    interview["pending_category"] = category
    interview["pending_question"] = question

    return state


# ============================================================
# CATEGORY QUESTION HELPERS
# ============================================================

def get_category_questions(
    category: str,
    language: str,
) -> List[str]:

    language = normalize_language(language)

    category_data = QUESTION_BANK.get(
        category,
        {},
    )

    questions = category_data.get(
        language
    )

    if questions:
        return questions

    return category_data.get(
        "urdu",
        [],
    )


def get_category_question_index(
    state: Dict[str, Any],
    category: str,
) -> int:

    language = get_question_language(state)

    questions = get_category_questions(
        category,
        language,
    )

    if not questions:
        return 0

    count = 0

    for question in questions:

        if question_already_asked(
            state,
            question,
        ):
            count += 1

    return count


# ============================================================
# CATEGORY SELECTION
# ============================================================

def choose_next_category(
    state: Dict[str, Any],
) -> Optional[str]:

    ensure_interview_structure(state)

    interview = get_interview(state)

    current_category = interview.get(
        "current_category"
    )

    language = get_question_language(state)

    # --------------------------------------------------------
    # Continue current category
    # --------------------------------------------------------

    if current_category in CATEGORY_ORDER:

        questions = get_category_questions(
            current_category,
            language,
        )

        asked_count = get_category_question_index(
            state,
            current_category,
        )

        if asked_count < len(questions):
            return current_category

        interview["current_category"] = None

    # --------------------------------------------------------
    # Find next category
    # --------------------------------------------------------

    for category in CATEGORY_ORDER:

        questions = get_category_questions(
            category,
            language,
        )

        if not questions:
            continue

        asked_count = get_category_question_index(
            state,
            category,
        )

        if asked_count < len(questions):
            return category

    return None

# ============================================================
# QUESTION SELECTION
# ============================================================

def select_next_question(
    state: Dict[str, Any],
    category: str,
) -> Optional[str]:
    """
    Select and record the next unused question.

    The category is explicitly passed into record_question()
    so the pending question/category pair can never become
    ambiguous.
    """

    questions = get_category_questions(
        category,
        get_question_language(state),
    )

    if not questions:
        return None

    for question in questions:

        if not question_already_asked(
            state,
            question,
        ):

            record_question(
                state,
                question,
                category,
            )

            return question

    return None


# ============================================================
# PROBING
# ============================================================

def get_probe_question(
    state: Dict[str, Any],
    category: str,
) -> Optional[str]:
    """
    Return the first-level probe for a category.
    """

    questions = get_category_questions(
        category,
        get_question_language(state),
    )

    if category in (
        "skills",
        "work",
        "education",
    ):

        if len(questions) >= 2:
            return questions[1]

    return None


def get_vague_answer_probe(
    state: Dict[str, Any],
    category: str,
) -> Optional[str]:
    """
    Return the stronger vague-answer probe.

    Currently defined explicitly for skills.
    """

    if category != "skills":
        return None

    questions = get_category_questions(
        category,
        get_question_language(state),
    )

    if len(questions) >= 3:
        return questions[2]

    return None


def handle_vague_answer(
    state: Dict[str, Any],
) -> Optional[str]:
    """
    Handle a vague candidate answer.

    Rules:
    - Maximum one vague probe per category.
    - Never repeat a question.
    - Probe remains in the same category.
    """

    ensure_interview_structure(state)

    interview = state["interview"]

    category = interview.get(
        "current_category"
    )

    if not category:
        return None

    probed_categories = interview.setdefault(
        "vague_probe_categories",
        [],
    )

    # --------------------------------------------------------
    # Only one vague probe per category
    # --------------------------------------------------------

    if category in probed_categories:
        return None

    probe = get_probe_question(
        state,
        category,
    )

    # --------------------------------------------------------
    # If first probe was already used, try stronger probe
    # --------------------------------------------------------

    if (
        probe
        and question_already_asked(
            state,
            probe,
        )
    ):
        probe = get_vague_answer_probe(
            state,
            category,
        )

    if not probe:

        probe = get_vague_answer_probe(
            state,
            category,
        )

    if not probe:
        return None

    if question_already_asked(
        state,
        probe,
    ):
        return None

    # --------------------------------------------------------
    # IMPORTANT:
    # Probe belongs to the SAME category.
    # --------------------------------------------------------

    record_question(
        state,
        probe,
        category,
    )

    if category not in probed_categories:
        probed_categories.append(category)

    interview["vague_answer_probed"] = True

    state["next_question"] = probe

    return probe


# ============================================================
# ANSWER RECORDING
# ============================================================

def mark_answer(
    state: Dict[str, Any],
    answer: str,
    category: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Record one candidate answer against the exact question
    that was pending BEFORE the answer arrived.

    IMPORTANT:
    pending_question and pending_category are authoritative.

    This prevents an answer from being attached to a later
    category/question because another part of the graph changed
    current_category/current_question.
    """

    ensure_interview_structure(state)

    if answer is None:
        return state

    answer = str(answer).strip()

    if not answer:
        return state

    interview = state["interview"]

    # --------------------------------------------------------
    # CAPTURE PENDING CONTEXT FIRST
    # --------------------------------------------------------

    pending_category = interview.get(
        "pending_category"
    )

    pending_question = interview.get(
        "pending_question"
    )

    # --------------------------------------------------------
    # Backward-compatible fallback
    # --------------------------------------------------------

    if not pending_category:
        pending_category = category

    if not pending_category:
        pending_category = interview.get(
            "current_category"
        )

    if not pending_question:
        pending_question = interview.get(
            "current_question"
        )

    # --------------------------------------------------------
    # Never create an orphan answer
    # --------------------------------------------------------

    if not pending_category:
        return state

    # --------------------------------------------------------
    # Create immutable answer record
    # --------------------------------------------------------

    answer_record = {
        "category": pending_category,
        "question": pending_question,
        "answer": answer,
    }

    interview["answers"].append(
        answer_record
    )

    # --------------------------------------------------------
    # Category-specific evidence
    # --------------------------------------------------------

    evidence_mapping = {
        "skills": "skills_evidence",
        "work": "work_evidence",
        "education": "education_evidence",
        "family": "family_evidence",
        "open_talk": "open_talk_evidence",
    }

    evidence_field = evidence_mapping.get(
        pending_category
    )

    if evidence_field:

        interview.setdefault(
            evidence_field,
            [],
        )

        interview[evidence_field].append(
            answer
        )

    # --------------------------------------------------------
    # QUESTION HAS NOW BEEN ANSWERED
    #
    # Clear only the pending pair.
    #
    # current_category/current_question can remain temporarily
    # available to the advancement logic.
    # --------------------------------------------------------

    interview["pending_question"] = None
    interview["pending_category"] = None

    return state




# ============================================================
# CATEGORY COMPLETION
# ============================================================

def mark_category_complete(
    state: Dict[str, Any],
    category: str,
) -> Dict[str, Any]:
    """
    Explicitly mark a category complete.
    """

    ensure_interview_structure(state)

    interview = state["interview"]

    if interview.get(
        "current_category"
    ) == category:

        interview["current_category"] = None

    interview["current_question"] = None

    # --------------------------------------------------------
    # Clear pending context
    # --------------------------------------------------------

    interview["pending_question"] = None
    interview["pending_category"] = None

    interview["vague_answer_probed"] = False

    return state


# ============================================================
# STAGE 2
# ============================================================

def get_materials_question(
    state: Dict[str, Any],
) -> str:
    """
    Return Stage 2 materials/open invitation.
    """

    language = get_question_language(state)

    return MATERIALS_QUESTIONS.get(
        language,
        MATERIALS_QUESTIONS["urdu"],
    )


# ============================================================
# STAGE 3 NEXT QUESTION
# ============================================================

def get_next_interview_question(
    state: Dict[str, Any],
) -> Optional[str]:
    """
    Get the next Stage 3 interview question.

    This function only generates the next question.
    """

    ensure_interview_structure(state)

    interview = state["interview"]

    # --------------------------------------------------------
    # Already complete
    # --------------------------------------------------------

    if interview.get(
        "interview_complete",
        False,
    ):

        state["next_question"] = None

        return None

    # --------------------------------------------------------
    # Select category
    # --------------------------------------------------------

    category = choose_next_category(
        state
    )

    if not category:

        interview["interview_complete"] = True
        state["interview_complete"] = True
        state["next_question"] = None

        return None

    interview["current_category"] = category

    # --------------------------------------------------------
    # Select question
    # --------------------------------------------------------

    question = select_next_question(
        state,
        category,
    )

    if question:

        state["next_question"] = question

        # IMPORTANT:
        # This question is now waiting for the candidate's
        # next message. Save the exact question/category pair.
        interview["current_question"] = question
        interview["pending_question"] = question
        interview["pending_category"] = category

        return question

    # --------------------------------------------------------
    # Unexpected exhausted category
    # --------------------------------------------------------

    interview["current_category"] = None
    interview["current_question"] = None

    interview["pending_question"] = None
    interview["pending_category"] = None

    interview["vague_answer_probed"] = False

    next_category = choose_next_category(
        state
    )

    if not next_category:

        interview["interview_complete"] = True
        state["interview_complete"] = True
        state["next_question"] = None

        return None

    interview["current_category"] = next_category

    question = select_next_question(
        state,
        next_category,
    )

    if not question:

        interview["interview_complete"] = True
        state["interview_complete"] = True
        state["next_question"] = None


        interview["current_question"] = None
        interview["pending_question"] = None
        interview["pending_category"] = None

        return None

    state["next_question"] = question

    # IMPORTANT:
    # Save the newly generated question as the pending question.
    interview["current_question"] = question
    interview["pending_question"] = question
    interview["pending_category"] = next_category

    return question

# ============================================================
# MAIN QUESTION ENGINE
# ============================================================

def generate_next_question(
    state: Dict[str, Any],
) -> Optional[str]:
    """
    Main public question-generation function.

    Stage 2:
        Materials/open invitation.

    Stage 3:
        Deep interview.

    Other stages:
        None.
    """

    stage = state.get(
        "stage",
        STAGE_INITIAL,
    )

    if stage == STAGE_MATERIALS:

        return get_materials_question(
            state
        )

    if stage == STAGE_INTERVIEW:

        return get_next_interview_question(
            state
        )

    return None


# ============================================================
# LANGGRAPH INTERVIEW NODE
# ============================================================

def interview_node(
    state: Dict[str, Any],
) -> Dict[str, Any]:
    """
    LangGraph-compatible interview node.

    Stage 2:
        Generates materials/open invitation.

    Stage 3:
        Generates exactly one pending interview question.

    IMPORTANT:
    If process_answer() already generated a probe,
    this node preserves that probe.
    """

    ensure_interview_structure(state)

    stage = state.get(
        "stage",
        STAGE_INITIAL,
    )

    # --------------------------------------------------------
    # STAGE 2
    # --------------------------------------------------------

    if stage == STAGE_MATERIALS:

        question = get_materials_question(
            state
        )

        state["next_question"] = question

        return state

    # --------------------------------------------------------
    # STAGE 3
    # --------------------------------------------------------

    if stage == STAGE_INTERVIEW:

        interview = state["interview"]

        # ----------------------------------------------------
        # If a question is already waiting for the candidate,
        # NEVER generate another one.
        # ----------------------------------------------------

        existing_question = interview.get(
            "pending_question"
        )

        if existing_question:

            state["next_question"] = (
                existing_question
            )

            return state

        # ----------------------------------------------------
        # Backward-compatible check
        # ----------------------------------------------------

        existing_question = state.get(
            "next_question"
        )

        if existing_question:

            # Make sure the question is also registered as pending.
            interview["current_question"] = existing_question

            if not interview.get("pending_question"):
                interview["pending_question"] = existing_question

            if not interview.get("pending_category"):
                interview["pending_category"] = (
                    interview.get("current_category")
                )

            state["next_question"] = existing_question

            return state

        # ----------------------------------------------------
        # Interview already complete
        # ----------------------------------------------------

        if interview.get(
            "interview_complete",
            False,
        ):

            state["next_question"] = None

            return state

        # ----------------------------------------------------
        # Generate exactly one new question
        # ----------------------------------------------------

        question = get_next_interview_question(
            state
        )

        state["next_question"] = question

        if question:

            state["interview_started"] = True

        else:

            state["interview_complete"] = True

            state["interview"][
                "interview_complete"
            ] = True

        return state

    # --------------------------------------------------------
    # OTHER STAGES
    # --------------------------------------------------------

    state["next_question"] = None

    return state


# ============================================================
# ADVANCE AFTER ANSWER
# ============================================================

def advance_after_answer(
    state: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Advance the interview after an answer.

    Does NOT generate the next question.

    The next question is generated by interview_node().
    """

    ensure_interview_structure(state)

    interview = state["interview"]

    current_category = interview.get(
        "current_category"
    )

    if not current_category:
        return state

    questions = get_category_questions(
        current_category,
        get_question_language(state),
    )

    asked_count = get_category_question_index(
        state,
        current_category,
    )

    # --------------------------------------------------------
    # Category still has questions
    # --------------------------------------------------------

    if asked_count < len(questions):

        # Current category remains active.
        #
        # But there is no pending question now because the
        # previous question has already been answered.

        interview["pending_question"] = None
        interview["pending_category"] = None

        return state

    # --------------------------------------------------------
    # Category exhausted
    # --------------------------------------------------------

    interview["current_category"] = None
    interview["current_question"] = None

    interview["pending_question"] = None
    interview["pending_category"] = None

    interview["vague_answer_probed"] = False

    # --------------------------------------------------------
    # Open talk is final
    # --------------------------------------------------------

    if current_category == "open_talk":

        interview["interview_complete"] = True

        state["interview_complete"] = True
        state["next_question"] = None

        return state

    # --------------------------------------------------------
    # Check next category
    # --------------------------------------------------------

    next_category = choose_next_category(
        state
    )

    if next_category is None:

        interview["interview_complete"] = True

        state["interview_complete"] = True
        state["next_question"] = None

        return state

    # --------------------------------------------------------
    # Do NOT generate next question here.
    #
    # interview_node() will do that on the next graph cycle.
    # --------------------------------------------------------

    interview["current_category"] = next_category

    return state


# ============================================================
# INTERVIEW COMPLETION CHECK
# ============================================================

def is_interview_complete(
    state: Dict[str, Any],
) -> bool:
    """
    Determine whether Stage 3 interview is complete.
    """

    interview = get_interview(state)

    if interview.get(
        "interview_complete",
        False,
    ):
        return True

    if state.get(
        "interview_complete",
        False,
    ):
        return True

    # --------------------------------------------------------
    # If a question is currently pending, the interview
    # absolutely cannot be complete.
    # --------------------------------------------------------

    if interview.get(
        "pending_question"
    ):
        return False

    # --------------------------------------------------------
    # Check every category
    # --------------------------------------------------------

    for category in CATEGORY_ORDER:

        questions = get_category_questions(
            category,
            get_question_language(state),
        )

        if not questions:
            continue

        asked_count = get_category_question_index(
            state,
            category,
        )

        if asked_count < len(questions):
            return False

    return True


# ============================================================
# COMPLETE INTERVIEW
# ============================================================

def complete_interview(
    state: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Mark the interview as complete.

    Does not perform scoring.
    """

    ensure_interview_structure(state)

    interview = state["interview"]

    interview["interview_complete"] = True

    interview["pending_question"] = None
    interview["pending_category"] = None

    state["interview_complete"] = True
    state["next_question"] = None

    return state


# ============================================================
# INTERVIEW STATUS
# ============================================================

def get_interview_status(
    state: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Return a compact interview status object.
    """

    ensure_interview_structure(state)

    interview = get_interview(state)

    answers = interview.get(
        "answers",
        [],
    )

    questions = interview.get(
        "questions_asked",
        [],
    )

    return {
        "stage": state.get(
            "stage"
        ),

        "language": normalize_language(
            state.get("language")
        ),

        "current_category": interview.get(
            "current_category"
        ),

        "current_question": interview.get(
            "current_question"
        ),

        "pending_category": interview.get(
            "pending_category"
        ),

        "pending_question": interview.get(
            "pending_question"
        ),

        "questions_asked": len(
            questions
            if isinstance(questions, list)
            else []
        ),

        "answers_recorded": len(
            answers
            if isinstance(answers, list)
            else []
        ),

        "vague_probe_used": bool(
            interview.get(
                "vague_answer_probed",
                False,
            )
        ),

        "probe_categories": interview.get(
            "vague_probe_categories",
            [],
        ),

        "interview_complete": bool(
            interview.get(
                "interview_complete",
                False,
            )
        ),

        "next_question": state.get(
            "next_question"
        ),
    }

# ============================================================================
# CANDIDATE FIELDS
# ============================================================================

CANDIDATE_FIELDS = {
    "name",
    "phone_number",
    "age",
    "location",
    "experience",
    "current_job",
    "skills",
    "work_history",
    "education",
    "father_occupation",
    "brothers",
    "living_situation",
    "housing_status",
    "background",
    "additional_information",
}


LIST_FIELDS = {
    "skills",
    "work_history",
}

BASIC_REQUIRED_FIELDS = [
    "name",
    "age",
    "location",
    "experience",
]

# ============================================================================
# VALUE CLEANING
# ============================================================================

def _clean_value(
    value: Any,
) -> Any:

    if value is None:
        return None

    if isinstance(value, str):

        value = value.strip()

        if not value:
            return None

        if value.lower() in {
            "null",
            "none",
            "n/a",
            "na",
            "not provided",
            "unknown",
            "not mentioned",
            "not specified",
        }:
            return None

    return value


# ============================================================================
# CANDIDATE MERGING
# ============================================================================

def _merge_candidate_data(
    existing: Dict[str, Any],
    extracted: Dict[str, Any],
) -> Dict[str, Any]:

    result = deepcopy(
        existing or {}
    )

    for field in CANDIDATE_FIELDS:

        if field not in extracted:
            continue

        new_value = _clean_value(
            extracted.get(field)
        )

        if new_value is None:
            continue

        # LIST FIELDS
        if field in LIST_FIELDS:

            if not isinstance(
                new_value,
                list,
            ):
                new_value = [
                    new_value
                ]

            cleaned_values = []

            for item in new_value:

                cleaned_item = _clean_value(
                    item
                )

                if cleaned_item is not None:
                    cleaned_values.append(
                        cleaned_item
                    )

            if not cleaned_values:
                continue

            old_value = result.get(
                field,
                []
            )

            if not isinstance(
                old_value,
                list,
            ):
                old_value = [
                    old_value
                ]

            combined = (
                old_value
                + cleaned_values
            )

            unique_values = []

            for item in combined:

                if item not in unique_values:
                    unique_values.append(
                        item
                    )

            result[field] = unique_values

            continue

        # NORMAL FIELD
        result[field] = new_value

    return result


# ============================================================================

def _extract_name(
    message: str,
) -> str | None:

    patterns = [
        r"\bmy name is\s+([A-Za-z][A-Za-z .'-]{1,50})",
        r"\bname[:\-]\s*([A-Za-z][A-Za-z .'-]{1,50})",
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            message,
            re.IGNORECASE,
        )

        if not match:
            continue

        value = match.group(1).strip()

        value = re.split(
            r"\b(?:and|i live|i have|from)\b",
            value,
            flags=re.IGNORECASE,
        )[0].strip()

        if value:
            return value

    return None


# ============================================================================
# LOCAL AGE EXTRACTION
# ============================================================================

def _extract_age(
    message: str,
) -> int | None:

    patterns = [
        r"\b(\d{1,3})\s*(?:years old|year old)\b",
        r"\bage\s*(?:is|:)?\s*(\d{1,3})\b",
        r"\biam\s*(\d{1,3})\b",
        r"\bi am\s*(\d{1,3})\b",
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            message,
            re.IGNORECASE,
        )

        if match:

            try:
                age = int(
                    match.group(1)
                )

                if 10 <= age <= 100:
                    return age

            except Exception:
                pass

    return None


# ============================================================================
# LOCAL LOCATION EXTRACTION
# ============================================================================

def _extract_location(
    message: str,
) -> str | None:

    patterns = [
        r"\bi live in\s+([A-Za-z][A-Za-z .,'-]{1,60})",
        r"\bi'm from\s+([A-Za-z][A-Za-z .,'-]{1,60})",
        r"\bi am from\s+([A-Za-z][A-Za-z .,'-]{1,60})",
        r"\bfrom\s+([A-Za-z][A-Za-z .,'-]{1,60})",
        r"\blive in\s+([A-Za-z][A-Za-z .,'-]{1,60})",
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            message,
            re.IGNORECASE,
        )

        if not match:
            continue

        value = match.group(1).strip()

        value = re.split(
            r"\b(?:and|i have|i am|i'm|with)\b",
            value,
            flags=re.IGNORECASE,
        )[0].strip(
            " .,;-"
        )

        if value:
            return value

    return None


# ============================================================================
# LOCAL EXPERIENCE EXTRACTION
# ============================================================================

def _extract_experience(
    message: str,
) -> str | None:

    if not message:
        return None

    text = str(message).strip()

    patterns = [
        r"\b(\d+(?:\.\d+)?)\s*(?:years?|yrs?)\s+(?:of\s+)?(?:[\w\s-]{1,40}\s+)?experience\b",
        r"\bexperience\s*(?:of|:)?\s*(\d+(?:\.\d+)?)\s*years?\b",
        r"\bworking\s+(?:for|in)\s+(\d+(?:\.\d+)?)\s*years?\b",
        r"\bworked\s+(?:for|in)\s+(\d+(?:\.\d+)?)\s*years?\b",
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            re.IGNORECASE,
        )

        if match:

            value = match.group(1)

            return f"{value} years"

    return None


# ============================================================================
# LOCAL CANDIDATE EXTRACTION
# ============================================================================

def _local_extract_candidate(
    message: str,
    existing: Dict[str, Any] | None = None,
) -> Dict[str, Any]:

    extracted: Dict[str, Any] = {}

    name = _extract_name(
        message
    )

    if name:
        extracted["name"] = name

    age = _extract_age(
        message
    )

    if age is not None:
        extracted["age"] = age

    location = _extract_location(
        message
    )

    if location:
        extracted["location"] = location

    experience = _extract_experience(
        message
    )

    if experience:
        extracted["experience"] = experience

    # ------------------------------------------------------------------------
    # Current job / skills
    # ------------------------------------------------------------------------

    lower = message.lower()

    job_patterns = [
        r"\bi work in\s+(.+)",
        r"\bi work as\s+(.+)",
        r"\bcurrently work in\s+(.+)",
        r"\bcurrently work as\s+(.+)",
        r"\bworking in\s+(.+)",
        r"\bworking as\s+(.+)",
    ]

    for pattern in job_patterns:

        match = re.search(
            pattern,
            message,
            re.IGNORECASE,
        )

        if match:

            value = match.group(1).strip()

            value = re.split(
                r"[.!?\n]",
                value
            )[0].strip()

            if value:
                extracted["current_job"] = value
                break

    skill_terms = [
        "sales",
        "marketing",
        "coding",
        "programming",
        "python",
        "javascript",
        "shopify",
        "automation",
        "ai",
        "design",
        "graphic design",
        "video editing",
        "customer service",
        "management",
    ]

    found_skills = []

    for skill in skill_terms:

        if skill in lower:
            found_skills.append(
                skill
            )

    if found_skills:
        extracted["skills"] = found_skills

    # ------------------------------------------------------------------------
    # Education
    # ------------------------------------------------------------------------

    education_patterns = [
        r"\bi studied\s+(.+)",
        r"\bstudied\s+(.+)",
        r"\beducation\s*:\s*(.+)",
        r"\bdegree\s*:\s*(.+)",
    ]

    for pattern in education_patterns:

        match = re.search(
            pattern,
            message,
            re.IGNORECASE,
        )

        if match:

            value = match.group(1).strip()

            value = re.split(
                r"[.!?\n]",
                value
            )[0].strip()

            if value:
                extracted["education"] = value
                break

    return extracted


# ============================================================================
# OPTIONAL GEMINI EXTRACTION
# ============================================================================

def _gemini_extract_candidate(
    message: str,
) -> Dict[str, Any]:

    if not gemini_client:
        return {}

    prompt = f"""
You are extracting candidate information for Talent Live.

Return ONLY valid JSON.

Extract only information explicitly present in the message.

Allowed fields:
name
age
location
experience
current_job
skills
work_history
education
father_occupation
brothers
living_situation
housing_status
background
additional_information

Rules:
- Never invent information.
- Missing fields must be null.
- skills and work_history must be arrays.
- age must be a number when available.

Candidate message:

{message}
"""

    try:

        response = gemini_client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
        )

        return _safe_json_loads(
            getattr(
                response,
                "text",
                ""
            )
        )

    except Exception as exc:

        print(
            f"[Gemini extraction error] {exc}"
        )

        return {}


# ============================================================================
# REQUIRED FIELD CHECK
# ============================================================================

def get_missing_basic_fields(
    candidate: Dict[str, Any],
) -> List[str]:

    missing = []

    candidate = (
        candidate
        or {}
    )

    for field in BASIC_REQUIRED_FIELDS:

        value = candidate.get(
            field
        )

        if value is None:
            missing.append(
                field
            )
            continue

        if isinstance(
            value,
            str,
        ) and not value.strip():
            missing.append(
                field
            )

    return missing


# ============================================================================
# NEXT BASIC QUESTION
# ============================================================================

def generate_next_basic_question(
    candidate: Dict[str, Any],
    language: str,
) -> str:

    missing = get_missing_basic_fields(
        candidate
    )

    field = (
        missing[0]
        if missing
        else None
    )

    if language == "english":

        questions = {
            "name": "What's your name?",
            "age": "How old are you?",
            "location": "Where do you live?",
            "experience": "How much work experience do you have, and what kind of work have you done?",
        }

    elif language == "roman_urdu":

        questions = {
            "name": "Aap ka naam kya hai?",
            "age": "Aap ki age kya hai?",
            "location": "Aap kahan rehte hain?",
            "experience": "Aap ka kitna work experience hai aur kis type ka kaam kiya hai?",
        }

    else:

        questions = {
            "name": "آپ کا نام کیا ہے؟",
            "age": "آپ کی عمر کتنی ہے؟",
            "location": "آپ کہاں رہتے ہیں؟",
            "experience": "آپ کا کتنا کام کا تجربہ ہے اور آپ نے کس قسم کا کام کیا ہے؟",
        }

    return questions.get(
        field,
        "Tell me a little about yourself.",
    )


# ============================================================================
# TEXT NORMALIZATION
# ============================================================================

def _normalize_text(
    text: str,
) -> str:

    text = str(
        text or ""
    ).lower().strip()

    text = re.sub(
        r"\s+",
        " ",
        text,
    )

    return text


def _contains_any_phrase(
    text: str,
    phrases: set[str],
) -> bool:

    normalized = _normalize_text(
        text
    )

    for phrase in phrases:

        if phrase in normalized:
            return True

    return False

# ============================================================================
# MATERIAL KEYWORDS
# ============================================================================

MATERIAL_KEYWORDS = {
    "cv",
    "resume",
    "curriculum vitae",
    "github",
    "git hub",
    "portfolio",
    "certificate",
    "certificates",
    "recommendation",
    "recommendations",
    "past work",
    "work sample",
    "work samples",
    "document",
    "documents",
    "file",
    "files",
}


MATERIAL_SKIP_PHRASES = {
    "no cv",
    "no resume",
    "no curriculum vitae",
    "don't have a cv",
    "dont have a cv",
    "do not have a cv",
    "don't have resume",
    "dont have resume",
    "do not have resume",
    "i have no cv",
    "i have no resume",

    "no github",
    "don't have github",
    "dont have github",
    "do not have github",
    "i have no github",

    "no portfolio",
    "don't have portfolio",
    "dont have portfolio",
    "do not have portfolio",
    "i have no portfolio",

    "nothing to send",
    "nothing to share",

    "i don't have anything",
    "i dont have anything",
    "do not have anything",
    "i have nothing",

    "no documents",
    "no certificates",

    "can't send",
    "cannot send",
    "cant send",

    "skip",
    "skip this",
    "skip materials",
    "i want to skip",

    "move on",
    "let's move on",
    "lets move on",
}

# ============================================================================
# MATERIAL RESPONSE DETECTION
# ============================================================================

def detect_materials_response(
    message: str,
) -> str:

    """
    Returns:

        skip
        talk
        material
        unclear
    """

    text = _normalize_text(
        message
    )

    if not text:
        return "unclear"

    # ------------------------------------------------------------------------
    # Explicit skip phrases
    # ------------------------------------------------------------------------

    if _contains_any_phrase(
        text,
        MATERIAL_SKIP_PHRASES,
    ):
        return "skip"

    # ------------------------------------------------------------------------
    # Negative material phrases
    # ------------------------------------------------------------------------

    negative_patterns = [

        r"\b(?:i|we)\s+(?:do not|don't|dont)\s+have\s+(?:a\s+)?(?:cv|resume|github|portfolio|certificate|certificates|documents?|files?)\b",

        r"\b(?:i|we)\s+have\s+no\s+(?:cv|resume|github|portfolio|certificate|certificates|documents?|files?)\b",

        r"\b(?:i|we)\s+(?:do not|don't|dont)\s+have\s+any\s+(?:documents?|files?|materials?)\b",

        r"\b(?:i|we)\s+(?:do not|don't|dont)\s+have\s+anything\s+(?:to\s+send|to\s+share)\b",

        r"\bno\s+(?:cv|resume|github|portfolio|documents?|files?|certificates?)\b",
    ]

    for pattern in negative_patterns:

        if re.search(
            pattern,
            text,
            re.IGNORECASE,
        ):
            return "skip"

    # ------------------------------------------------------------------------
    # Candidate explicitly says they can just talk.
    # ------------------------------------------------------------------------

    talk_patterns = [

        r"\bi\s+can\s+just\s+tell\s+you",

        r"\bi\s+can\s+tell\s+you\s+about\s+my\s+work",

        r"\bi\s+can\s+tell\s+you\s+about\s+my\s+experience",

        r"\bjust\s+tell\s+you\s+about\s+my\s+work",

        r"\btell\s+you\s+about\s+my\s+work",

        r"\btell\s+you\s+about\s+my\s+experience",

        r"\bi\s+can\s+just\s+talk",

        r"\bi\s+will\s+just\s+talk",

        r"\bi\s+can\s+explain\s+my\s+work",

        r"\bi\s+can\s+explain\s+my\s+experience",

        r"\bno\s+cv\s+or\s+github",
    ]

    for pattern in talk_patterns:

        if re.search(
            pattern,
            text,
            re.IGNORECASE,
        ):
            return "talk"

    # ------------------------------------------------------------------------
    # If candidate mentions sending a material.
    # ------------------------------------------------------------------------

    for keyword in MATERIAL_KEYWORDS:

        if keyword in text:

            # Positive material mention.
            positive_patterns = [
                r"\bi\s+have\s+",
                r"\bi've\s+got\s+",
                r"\bi\s+can\s+send",
                r"\bi\s+will\s+send",
                r"\bhere\s+is",
                r"\battached",
                r"\bsending",
            ]

            for positive in positive_patterns:

                if re.search(
                    positive,
                    text,
                    re.IGNORECASE,
                ):
                    return "material"

    # ------------------------------------------------------------------------
    # Meaningful conversation should not get stuck in Stage 2.
    # ------------------------------------------------------------------------

    work_patterns = [

        r"\bmy\s+work\b",
        r"\bmy\s+experience\b",
        r"\bwork\s+experience\b",
        r"\bi\s+have\s+been\s+working\b",
        r"\bi\s+worked\b",
        r"\bi\s+currently\s+work\b",
        r"\bi\s+work\s+in\b",
        r"\bworking\s+in\b",
        r"\bmy\s+job\b",
        r"\bmy\s+career\b",
        r"\bmy\s+skills\b",
    ]

    for pattern in work_patterns:

        if re.search(
            pattern,
            text,
            re.IGNORECASE,
        ):
            return "talk"

    # Broad fallback.
    if len(
        text.split()
    ) >= 5:
        return "talk"

    return "unclear"


# ============================================================================
# MATERIALS INVITATION
# ============================================================================

def _materials_invitation(
    language: str,
) -> str:

    if language == "english":

        return (
            "If you've got a CV, GitHub, portfolio, "
            "certificates, past work, or anything else "
            "that shows what you can do, send it over — "
            "send as much or as little as you want, "
            "nothing's required.\n\n"
            "And beyond that, feel free to just talk. "
            "Don't worry about saying it perfectly or "
            "organizing it. Tell me about yourself, your "
            "work, or anything you think is worth knowing."
        )

    if language == "roman_urdu":

        return (
            "Agar aap ke paas CV, GitHub, portfolio, "
            "certificates, past work ya koi aur cheez "
            "hai jo aapki skills show karti hai to bhej "
            "sakte hain. Jitna chahein bhejein, kuch bhi "
            "lazmi nahi hai.\n\n"
            "Is ke ilawa apne bare mein, apne kaam ke "
            "bare mein, ya kisi bhi aisi cheez ke bare "
            "mein freely bata sakte hain jo aap ke "
            "khayal mein maloom honi chahiye."
        )

    return (
        "اگر آپ کے پاس CV، GitHub، portfolio، "
        "certificates، past work یا کوئی اور چیز ہے "
        "جو آپ کی skills دکھاتی ہے تو بھیج سکتے ہیں۔ "
        "جتنا چاہیں بھیجیں، کچھ بھی لازمی نہیں ہے۔\n\n"
        "اس کے علاوہ اپنے بارے میں، اپنے کام کے بارے "
        "میں، یا کسی بھی ایسی چیز کے بارے میں freely "
        "بتا سکتے ہیں جو آپ کے خیال میں معلوم ہونی چاہیے۔"
    )


# ============================================================================
# FALLBACK INTERVIEW QUESTION
# ============================================================================

def _fallback_interview_question(
    language: str,
) -> str:

    if language == "english":

        return (
            "Let's start with your work experience. "
            "Tell me about the kind of work you have done "
            "and what responsibilities you handled."
        )

    if language == "roman_urdu":

        return (
            "Chaliye aap ke work experience se start karte hain. "
            "Aap ne kis tarah ka kaam kiya hai aur aapki "
            "kya responsibilities rahi hain?"
        )

    return (
        "آئیے آپ کے کام کے تجربے سے شروع کرتے ہیں۔ "
        "آپ نے کس طرح کا کام کیا ہے اور آپ کی "
        "کیا ذمہ داریاں رہی ہیں؟"
    )


# ============================================================================
# HELPER:
# WAS MATERIALS INVITATION ALREADY SENT?
# ============================================================================
#
# IMPORTANT FIX
#
# We do NOT rely on `materials_prompt_sent`.
#
# Instead we inspect:
#
# 1. materials_response_type
# 2. materials_skipped
# 3. materials_received
# 4. interview_started
# 5. conversation_history
#
# This makes Stage 2 survive LangGraph state filtering/reducers.
# ============================================================================

def _materials_invitation_already_sent(
    state: AgentState,
) -> bool:

    if state.get(
        "materials_response_type"
    ) in {
        "skip",
        "talk",
        "material",
    }:
        return True

    if state.get(
        "materials_skipped",
        False,
    ):
        return True

    if state.get(
        "materials_received",
        False,
    ):
        return True

    if state.get(
        "interview_started",
        False,
    ):
        return True

    # Durable marker: on the first Stage-2 pass, the invitation itself is
    # stored in next_question. This prevents the invitation from being sent
    # again even if a state flag is missing from the AgentState schema.
    current_question = str(
        state.get("next_question", "") or ""
    ).strip().lower()

    invitation_markers = (
        "if you've got a cv",
        "if you’ve got a cv",
        "agar aap ke paas cv",
        "اگر آپ کے پاس cv",
        "اگر آپ کے پاس سی وی",
    )

    if any(
        marker in current_question
        for marker in invitation_markers
    ):
        return True

    # Check conversation history.
    history = state.get(
        "conversation_history",
        [],
    ) or []

    if not isinstance(
        history,
        list,
    ):
        return False

    invitation_markers = [
        "If you've got a CV",
        "If you’ve got a CV",
        "Agar aap ke paas CV",
        "اگر آپ کے پاس CV",
    ]

    for item in history:

        if not isinstance(
            item,
            dict,
        ):
            continue

        if item.get(
            "role"
        ) != "assistant":
            continue

        content = str(
            item.get(
                "content",
                ""
            )
            or ""
        )

        for marker in invitation_markers:

            if marker.lower() in content.lower():
                return True

    return False


# ============================================================================


def detect_language(message: str) -> str:
    """
    Detect:
        urdu
        roman_urdu
        english
    """

    if not message:
        return "urdu"

    text = str(message).strip()

    if not text:
        return "urdu"

    urdu_script_count = sum(
        1
        for char in text
        if "\u0600" <= char <= "\u06ff"
    )

    if urdu_script_count > 0:
        return "urdu"

    lower_text = text.lower()

    roman_urdu_words = {
        "mera", "meri", "mere", "mujhe", "mujhy",
        "mein", "main", "hum", "ham", "hai", "hain",
        "tha", "thi", "the", "saal", "umar", "naam",
        "rehta", "rehti", "rehte", "kaam", "karta",
        "karti", "karte", "tajurba", "shehar", "ghar",
        "walid", "walidain", "abba", "ami", "bhai",
        "behen", "behna", "parhai", "parha", "parhi",
        "kahan", "apna", "apne", "aap", "aapki", "aapka",
        "batayein", "bataein", "batao", "karna", "karne",
        "mujh", "liye", "acha", "achi", "achay",
    }

    words = {
        word.strip(".,!?;:()[]{}\"'`")
        for word in lower_text.split()
    }

    roman_matches = len(
        words.intersection(
            roman_urdu_words
        )
    )

    if roman_matches >= 2:
        return "roman_urdu"

    return "english"

def candidate_extraction_node(
    state: AgentState,
) -> AgentState:

    state = deepcopy(state)

    message = (
        state.get(
            "message",
            "",
        )
        or ""
    )

    message = str(message).strip()

    if not message:
        return state

    state["last_user_message"] = message
    state["candidate_responded"] = True

    if not state.get("language_locked", False):

        state["language"] = detect_language(message)
        state["language_locked"] = True

    language = (
        state.get("language", "english")
        or "english"
    )

    # ------------------------------------------------------------------------
    # IMPORTANT STAGE 3 PROTECTION
    #
    # Once the interview has started, the candidate's message is an interview
    # answer. Do not let the generic candidate extractor reinterpret that
    # answer as a new basic-information response.
    # ------------------------------------------------------------------------

    current_stage = int(
        state.get(
            "stage",
            STAGE_INITIAL,
        )
        or STAGE_INITIAL
    )

    if current_stage >= STAGE_INTERVIEW:

        state["last_user_message"] = message
        state["candidate_responded"] = True

        # Stage 3 owns the message now.
        return state

    # ------------------------------------------------------------------------
    # STAGE 0 / 1 CANDIDATE EXTRACTION
    # ------------------------------------------------------------------------

    existing_candidate = (
        state.get("candidate", {})
        or {}
    )

    missing_before_extraction = get_missing_basic_fields(
    existing_candidate
    )

    expected_field = (
        missing_before_extraction[0]
        if missing_before_extraction
        else None
    )

    local_extracted = _local_extract_candidate(
        message=message,
        existing=existing_candidate,
        expected_field=expected_field,
    )

    extracted = local_extracted

    if USE_GEMINI_EXTRACTION and gemini_client:

        gemini_data = _gemini_extract_candidate(
            message
        )

        if gemini_data:

            extracted = _merge_candidate_data(
                local_extracted,
                gemini_data,
            )

    merged_candidate = _merge_candidate_data(
        existing_candidate,
        extracted,
    )

    if state.get("phone_number"):

        merged_candidate["phone_number"] = (
            state["phone_number"]
        )

    state["candidate"] = merged_candidate

    extracted_fields = [
        key
        for key in extracted.keys()
        if key in CANDIDATE_FIELDS
    ]

    if extracted_fields:

        notes = state.setdefault(
            "system_notes",
            [],
        )

        note = (
            "Candidate information extracted: "
            + ", ".join(extracted_fields)
        )

        if note not in notes:
            notes.append(note)

    missing_fields = get_missing_basic_fields(
        merged_candidate
    )

    if current_stage <= STAGE_BASIC:

        if not missing_fields:

            previous_stage = current_stage

            state["stage"] = STAGE_MATERIALS
            state["previous_stage"] = previous_stage
            state["stage_changed"] = (
                previous_stage != STAGE_MATERIALS
            )

        else:

            state["stage"] = STAGE_BASIC
            state["stage_changed"] = (
                current_stage != STAGE_BASIC
            )

    return state


# ============================================================================
# MATERIALS STAGE NODE
# ============================================================================

def materials_stage_node(
    state: AgentState,
) -> AgentState:

    state = deepcopy(state)

    current_stage = int(
        state.get(
            "stage",
            STAGE_INITIAL,
        )
        or STAGE_INITIAL
    )

    if current_stage != STAGE_MATERIALS:
        return state

    message = (
        state.get(
            "last_user_message",
            state.get(
                "message",
                "",
            ),
        )
        or ""
    )

    message = str(message).strip()

    invitation_already_sent = (
        _materials_invitation_already_sent(
            state
        )
    )

    if not invitation_already_sent:

        invitation = _materials_invitation(
            state.get(
                "language",
                "english",
            )
        )

        state["next_question"] = invitation
        state["materials_prompt_sent"] = True
        state["materials_response_type"] = None
        state["materials_skipped"] = False
        state["materials_received"] = False

        state.setdefault(
            "system_notes",
            [],
        ).append(
            "Stage 2 materials invitation sent."
        )

        return state

    response_type = detect_materials_response(
        message
    )

    state["materials_response_type"] = response_type

    if response_type in {"skip", "talk"}:

        state["materials_skipped"] = True
        state["materials_received"] = False

        previous_stage = current_stage

        state["stage"] = STAGE_INTERVIEW
        state["previous_stage"] = previous_stage
        state["stage_changed"] = True
        state["interview_started"] = True

        state["next_question"] = None

        # Clear any stale Stage 2 question snapshot.
        state["interview_active_question"] = None
        state["interview_active_category"] = None

        state.setdefault(
            "system_notes",
            [],
        ).append(
            "Stage 2 response detected: "
            + response_type
            + ". Starting Stage 3 interview."
        )

        return state

    if response_type == "material":

        state["materials_received"] = True
        state["materials_skipped"] = False

        previous_stage = current_stage

        state["stage"] = STAGE_INTERVIEW
        state["previous_stage"] = previous_stage
        state["stage_changed"] = True
        state["interview_started"] = True

        state["next_question"] = None

        state["interview_active_question"] = None
        state["interview_active_category"] = None

        state.setdefault(
            "system_notes",
            [],
        ).append(
            "Candidate provided/indicated material. "
            "Starting Stage 3 interview."
        )

        return state

    if message and len(message.split()) >= 3:

        state["materials_response_type"] = "talk"
        state["materials_skipped"] = True
        state["materials_received"] = False

        previous_stage = current_stage

        state["stage"] = STAGE_INTERVIEW
        state["previous_stage"] = previous_stage
        state["stage_changed"] = True
        state["interview_started"] = True

        state["next_question"] = None

        state["interview_active_question"] = None
        state["interview_active_category"] = None

        state.setdefault(
            "system_notes",
            [],
        ).append(
            "Meaningful Stage 2 response detected. "
            "Treating it as open conversation and starting Stage 3."
        )

        return state

    return state


def _snapshot_active_interview_question(
    state: AgentState,
) -> None:

    question = state.get(
        "next_question",
        "",
    )

    if (
        not isinstance(question, str)
        or not question.strip()
    ):
        return

    interview = (
        state.get(
            "interview",
            {},
        )
        or {}
    )

    if not isinstance(interview, dict):
        interview = {}

    category = interview.get(
        "current_category"
    )

    state["interview_active_question"] = (
        question.strip()
    )

    state["interview_active_category"] = (
        category
    )

def _restore_active_interview_question(
    state: AgentState,
) -> None:

    active_question = state.get(
        "interview_active_question",
        "",
    )

    active_category = state.get(
        "interview_active_category"
    )

    if (
        not isinstance(active_question, str)
        or not active_question.strip()
    ):
        return

    interview = (
        state.get(
            "interview",
            {},
        )
        or {}
    )

    if not isinstance(interview, dict):
        return

    answers = interview.get(
        "answers",
        [],
    )

    if not isinstance(answers, list) or not answers:
        return

    latest_answer = answers[-1]

    if isinstance(latest_answer, dict):

        latest_answer["question"] = (
            active_question
        )

        if active_category is not None:
            latest_answer["category"] = (
                active_category
            )

        if "question_text" in latest_answer:
            latest_answer["question_text"] = (
                active_question
            )

        if "question_category" in latest_answer:
            latest_answer["question_category"] = (
                active_category
            )

        if "current_category" in latest_answer:
            latest_answer["current_category"] = (
                active_category
            )

    interview["last_answer_question"] = (
        active_question
    )

    interview["last_answer_category"] = (
        active_category
    )

    state["interview"] = interview


# ============================================================
# INTERVIEW NODE
# ============================================================

def interview_stage_node(
    state: AgentState,
) -> AgentState:

    state = deepcopy(state)

    current_stage = int(
        state.get(
            "stage",
            STAGE_INITIAL,
        )
        or STAGE_INITIAL
    )

    if current_stage < STAGE_INTERVIEW:
        return state

    # ------------------------------------------------------------------------
    # If interview was already completed, move to Stage 4.
    # ------------------------------------------------------------------------

    if state.get("interview_complete", False):

        state["stage"] = STAGE_MODEL_EXPLANATION
        state["previous_stage"] = STAGE_INTERVIEW
        state["stage_changed"] = True
        state["interview_started"] = True
        state["next_question"] = None

        state.setdefault(
            "system_notes",
            [],
        ).append(
            "Interview already complete. "
            "Moving from Stage 3 to Stage 4."
        )

        return state

    message = (
        state.get(
            "last_user_message",
            state.get(
                "message",
                "",
            ),
        )
        or ""
    )

    message = str(message).strip()

    already_processed = (
        state.get(
            "interview_last_processed_message",
            "",
        )
        or ""
    )

    # ------------------------------------------------------------------------
    # Duplicate protection
    # ------------------------------------------------------------------------

    if message and message == already_processed:

        state["stage"] = STAGE_INTERVIEW
        state["interview_started"] = True

        return state

    # ------------------------------------------------------------------------
    # Determine whether a question is currently waiting for an answer.
    # ------------------------------------------------------------------------

    existing_question = state.get(
        "next_question"
    )

    has_existing_question = (
        isinstance(existing_question, str)
        and bool(existing_question.strip())
    )

    # ------------------------------------------------------------------------
    # FIRST STAGE 3 EXECUTION
    # ------------------------------------------------------------------------

    if not has_existing_question:

        try:

            state["stage"] = STAGE_INTERVIEW
            state["interview_started"] = True

            # ----------------------------------------------------------------
            # PERSIST CANDIDATE + CREATE INTERVIEW
            # ----------------------------------------------------------------

            interview_id = state.get(
                "interview_id"
            )

            if not interview_id:

                candidate = (
                    state.get(
                        "candidate",
                        {},
                    )
                    or {}
                )

                phone_number = state.get(
                    "phone_number"
                )

                candidate_data = {
                    "name": candidate.get("name"),
                    "language": candidate.get(
                        "language",
                        state.get(
                            "language",
                            "urdu",
                        ),
                    ),
                    "current_stage": STAGE_INTERVIEW,
                    "status": "active",
                    "engaged": True,
                }

                candidate_data = {
                    key: value
                    for key, value in candidate_data.items()
                    if value is not None
                }

                saved_candidate = upsert_candidate(
                    phone_number=phone_number,
                    candidate=candidate_data,
                )

                candidate_id = saved_candidate.get(
                    "id"
                )

                if not candidate_id:
                    raise RuntimeError(
                        "Stage 3 could not obtain candidate_id."
                    )

                state["candidate_id"] = candidate_id

                saved_interview = create_interview(
                    candidate_id=candidate_id,
                )

                interview_id = saved_interview.get(
                    "id"
                )

                if not interview_id:
                    raise RuntimeError(
                        "Stage 3 could not obtain interview_id."
                    )

                state["interview_id"] = interview_id

                state["interview_started_at"] = (
                    saved_interview.get(
                        "started_at"
                    )
                )

                state.setdefault(
                    "system_notes",
                    [],
                ).append(
                    "Supabase interview created: "
                    + str(interview_id)
                )

            # ----------------------------------------------------------------
            # START INTERVIEW ENGINE
            # ----------------------------------------------------------------

            interview_result = interview_node(
                state
            )

            if isinstance(
                interview_result,
                dict,
            ):

                state.update(
                    interview_result
                )

        except Exception as exc:

            print(
                f"[Interview initialization error] {exc}"
            )

            state.setdefault(
                "system_notes",
                [],
            ).append(
                "Interview initialization error: "
                + str(exc)
            )

        next_question = state.get(
            "next_question"
        )

        if (
            not isinstance(
                next_question,
                str,
            )
            or not next_question.strip()
        ):

            state["next_question"] = (
                _fallback_interview_question(
                    state.get(
                        "language",
                        "english",
                    )
                )
            )

        # ------------------------------------------------------------
        # IMPORTANT:
        # The newly generated question has now become the active
        # question waiting for the candidate's NEXT message.
        # ------------------------------------------------------------

        _snapshot_active_interview_question(
            state
        )

        return state

    # =========================================================================
    # EXISTING QUESTION = CURRENT MESSAGE IS THE ANSWER
    # =========================================================================

        # =========================================================================
    # EXISTING QUESTION = CURRENT MESSAGE IS THE ANSWER
    # =========================================================================

    if message:

        try:

            answer_result = process_answer(
                state,
                message,
            )

            if isinstance(
                answer_result,
                dict,
            ):
                state.update(
                    answer_result
                )

            state[
                "interview_last_processed_message"
            ] = message

        except Exception as exc:

            print(
                f"[Interview answer processing error] {exc}"
            )

            state.setdefault(
                "system_notes",
                [],
            ).append(
                "Interview answer processing error: "
                + str(exc)
            )

   
    # =========================================================================
    # STAGE 3 COMPLETION -> STAGE 4
    # =========================================================================

    interview_complete = bool(
        state.get(
            "interview_complete",
            False,
        )
    )

    if interview_complete:

        state["stage"] = STAGE_MODEL_EXPLANATION
        state["next_question"] = None
        state["interview_started"] = True
        state["previous_stage"] = STAGE_INTERVIEW
        state["stage_changed"] = True

        # No active question remains after completion.
        state["interview_active_question"] = None
        state["interview_active_category"] = None

        state.setdefault(
            "system_notes",
            [],
        ).append(
            "Interview completed. "
            "Moving to Stage 4 model explanation."
        )

        return state

    # =========================================================================
    # INTERVIEW REMAINS ACTIVE
    # =========================================================================

    state["stage"] = STAGE_INTERVIEW
    state["interview_started"] = True

    next_question = state.get(
        "next_question"
    )

    if (
        not isinstance(
            next_question,
            str,
        )
        or not next_question.strip()
    ):

        try:

            next_question = generate_next_question(
                state
            )

            state["next_question"] = (
                next_question
            )

        except Exception as exc:

            print(
                f"[Next interview question error] {exc}"
            )

            state.setdefault(
                "system_notes",
                [],
            ).append(
                "Next interview question error: "
                + str(exc)
            )

    if (
        not isinstance(
            state.get("next_question"),
            str,
        )
        or not state.get(
            "next_question",
            "",
        ).strip()
    ):

        state["next_question"] = (
            _fallback_interview_question(
                state.get(
                    "language",
                    "english",
                )
            )
        )

    # ------------------------------------------------------------------------
    # IMPORTANT:
    #
    # At this point next_question is the NEW question.
    # Therefore it becomes the active question for the NEXT user message.
    #
    # We intentionally do this AFTER the previous answer was restored.
    # ------------------------------------------------------------------------

    _snapshot_active_interview_question(
        state
    )

    return state


# ========================================================================
# STAGE 4 - MODEL EXPLANATION
# ========================================================================

def model_explanation_stage_node(
    state: AgentState,
) -> AgentState:

    state = deepcopy(state)

    current_stage = int(
        state.get(
            "stage",
            STAGE_INITIAL,
        )
        or STAGE_INITIAL
    )

    if current_stage != STAGE_MODEL_EXPLANATION:
        return state

    if state.get(
        "model_explanation_sent",
        False,
    ):
        return state

    language = (
        state.get(
            "language",
            "english",
        )
        or "english"
    )

    if language == "roman_urdu":

        explanation = (
            "Aap ka interview complete ho gaya hai. "
            "Ab main aap ko batata hoon ke Talent Live ka model "
            "kis tarah kaam karta hai.\n\n"
            "Main aise logon ka network build kar raha hoon "
            "jinhein unki skills ke mutabiq real work diya ja sake. "
            "Yeh Shopify, automation, e-commerce, sales, marketing "
            "ya kisi aur relevant area ka kaam ho sakta hai.\n\n"
            "Jab aapki skills ke mutabiq koi suitable kaam aata hai, "
            "main woh opportunity aap tak pohanchata hoon. "
            "Aap work complete karte hain, main client side handle karta hoon, "
            "aur aap ko completed work ka payment milta hai.\n\n"
            "Yeh Connect se bhi connected hai — Connect ek AI-driven agency "
            "hai jo Shopify beauty brands ke saath kaam karti hai. "
            "Is ke ilawa bhi doosre types ka work ho sakta hai, "
            "jo aapki skills ke mutabiq fit ho.\n\n"
            "Abhi maqsad sirf aap ko properly samajhna hai. "
            "Yeh process ka pehla step hai."
        )

    elif language == "urdu":

        explanation = (
            "آپ کا انٹرویو مکمل ہو گیا ہے۔ "
            "اب میں آپ کو بتاتا ہوں کہ Talent Live کا model "
            "کس طرح کام کرتا ہے۔\n\n"
            "میں ایسے لوگوں کا network build کر رہا ہوں "
            "جنہیں ان کی skills کے مطابق real work دیا جا سکے۔ "
            "یہ Shopify، automation، e-commerce، sales، marketing "
            "یا کسی اور relevant area کا کام ہو سکتا ہے۔\n\n"
            "جب آپ کی skills کے مطابق کوئی suitable کام آتا ہے، "
            "میں وہ opportunity آپ تک پہنچاتا ہوں۔ "
            "آپ work complete کرتے ہیں، میں client side handle کرتا ہوں، "
            "اور آپ کو completed work کی payment ملتی ہے۔\n\n"
            "یہ Connect سے بھی connected ہے — Connect ایک AI-driven agency "
            "ہے جو Shopify beauty brands کے ساتھ کام کرتی ہے۔ "
            "اس کے علاوہ بھی دوسرے types کا work ہو سکتا ہے، "
            "جو آپ کی skills کے مطابق fit ہو۔\n\n"
            "ابھی مقصد صرف آپ کو properly سمجھنا ہے۔ "
            "یہ process کا پہلا step ہے۔"
        )

    else:

        explanation = (
            "Thanks for sharing all that. Here's what this is about.\n\n"
            "I'm building a network of people I can send real work to — "
            "could be Shopify, automation, e-commerce, sales, marketing, "
            "depending on what fits you.\n\n"
            "When something comes up that matches your skills, "
            "I send it to you. You complete the work, I handle the "
            "client side, and you get paid for the work.\n\n"
            "This connects to Connect — an AI-driven agency I run "
            "working with Shopify beauty brands. There may be other "
            "kinds of work too, depending on what fits.\n\n"
            "Right now I want to get to know people properly before "
            "assigning anything, so this is just step one."
        )

    state["model_explanation"] = explanation
    state["model_explanation_sent"] = True
    state["next_question"] = None
    state["stage"] = STAGE_MODEL_EXPLANATION

    state.setdefault(
        "system_notes",
        [],
    ).append(
        "Stage 4 model explanation generated."
    )

    return state


# ============================================================================
# STAGE 5 - SCORING / LOGGING
# ============================================================================

def scoring_stage_node(
    state: AgentState,
) -> AgentState:

    state = deepcopy(state)

    current_stage = int(
        state.get(
            "stage",
            STAGE_INITIAL,
        )
        or STAGE_INITIAL
    )

    if state.get(
        "scoring_completed"
    ) is True:
        return state

    if current_stage not in (
        STAGE_MODEL_EXPLANATION,
        STAGE_SCORING,
    ):
        return state

    state["stage"] = STAGE_SCORING
    state["previous_stage"] = STAGE_MODEL_EXPLANATION
    state["stage_changed"] = True

    candidate = (
        state.get(
            "candidate",
            {},
        )
        or {}
    )

    if not isinstance(
        candidate,
        dict,
    ):
        candidate = {}

    phone_number = state.get(
        "phone_number"
    )

    candidate_data = {
        "name": candidate.get("name"),
        "language": candidate.get(
            "language",
            state.get(
                "language",
                "ur",
            ),
        ),
        "current_stage": STAGE_SCORING,
        "status": "completed",
        "engaged": True,
    }

    candidate_data = {
        key: value
        for key, value in candidate_data.items()
        if value is not None
    }

    saved_candidate = upsert_candidate(
        phone_number=phone_number,
        candidate=candidate_data,
    )

    candidate_id = saved_candidate["id"]

    state["candidate_id"] = candidate_id

    # ------------------------------------------------------------------------
    # USE EXISTING INTERVIEW
    # ------------------------------------------------------------------------

    interview_id = state.get(
        "interview_id"
    )

    if not interview_id:

        raise RuntimeError(
            "Stage 5 cannot continue: existing interview_id is missing."
        )

    state["interview_id"] = interview_id

    interview = (
        state.get(
            "interview",
            {},
        )
        or {}
    )

    if not isinstance(
        interview,
        dict,
    ):
        interview = {}

    questions = interview.get(
        "questions_asked",
        [],
    )

    answers = interview.get(
        "answers",
        [],
    )

    if not isinstance(
        questions,
        list,
    ):
        questions = []

    if not isinstance(
        answers,
        list,
    ):
        answers = []

    scoring_record = {
        "candidate_id": candidate_id,
        "phone_number": phone_number,
        "candidate": deepcopy(candidate),
        "interview_complete": bool(
            state.get(
                "interview_complete",
                False,
            )
        ),
        "questions_asked": deepcopy(
            questions
        ),
        "answers": deepcopy(
            answers
        ),
        "question_count": len(
            questions
        ),
        "answer_count": len(
            answers
        ),
    }

    state["scoring_record"] = scoring_record

    # ------------------------------------------------------------------------
    # RUN STAGE 5 SCORING ENGINE
    # ------------------------------------------------------------------------

    state = apply_score(
        state
    )

    print("\n" + "=" * 80)
    print("STAGE 5 SCORE DEBUG")
    print("=" * 80)

    print(
        "total_score:",
        state.get("total_score"),
    )

    print(
        "hunger_score:",
        state.get("hunger_score"),
    )

    print(
        "skill_score:",
        state.get("skill_score"),
    )

    print(
        "engagement_score:",
        state.get("engagement_score"),
    )

    print(
        "consistency_score:",
        state.get("consistency_score"),
    )

    print(
        "stability_score:",
        state.get("stability_score"),
    )

    print(
        "deductions_total:",
        state.get("deductions_total"),
    )

    print(
        "score_band:",
        state.get("score_band"),
    )

    print(
        "score_note:",
        state.get("score_note"),
    )

    print(
        "score_rationale:",
        state.get("score_rationale"),
    )

    print("=" * 80)

    total_score = state.get(
        "total_score"
    )

    hunger_score = state.get(
        "hunger_score"
    )

    skill_score = state.get(
        "skill_score"
    )

    engagement_score = state.get(
        "engagement_score"
    )

    consistency_score = state.get(
        "consistency_score"
    )

    stability_score = state.get(
        "stability_score"
    )

    deductions_total = state.get(
        "deductions_total"
    )

    score_band = state.get(
        "score_band"
    )

    if all(
        value is not None
        for value in (
            total_score,
            hunger_score,
            skill_score,
            engagement_score,
            consistency_score,
            stability_score,
            deductions_total,
            score_band,
        )
    ):

        saved_score = save_interview_score(
            candidate_id=candidate_id,
            interview_id=interview_id,
            total_score=int(
                total_score
            ),
            hunger_score=int(
                hunger_score
            ),
            skill_score=int(
                skill_score
            ),
            engagement_score=int(
                engagement_score
            ),
            consistency_score=int(
                consistency_score
            ),
            stability_score=int(
                stability_score
            ),
            deductions_total=int(
                deductions_total
            ),
            score_band=str(
                score_band
            ),
            score_note=state.get(
                "score_note"
            ),
            score_rationale=state.get(
                "score_rationale",
                {},
            ),
        )

        state["supabase_score_id"] = (
            saved_score["id"]
        )

        state["scoring_completed"] = True

        state["score"] = {
            "total_score": int(
                total_score
            ),
            "hunger_score": int(
                hunger_score
            ),
            "skill_score": int(
                skill_score
            ),
            "engagement_score": int(
                engagement_score
            ),
            "consistency_score": int(
                consistency_score
            ),
            "stability_score": int(
                stability_score
            ),
            "deductions_total": int(
                deductions_total
            ),
            "score_band": str(
                score_band
            ),
            "score_note": state.get(
                "score_note"
            ),
            "score_rationale": state.get(
                "score_rationale",
                {},
            ),
        }

    completion_time = (
        datetime.now(
            timezone.utc
        )
        + timedelta(
            seconds=1
        )
    )

    update_interview(
        interview_id=interview_id,
        updates={
            "current_stage": STAGE_SCORING,
            "status": "completed",
            "completed_at": completion_time.isoformat(),
            "completion_reason": (
                "Talent Live interview completed"
            ),
        },
    )

    update_candidate(
        candidate_id=candidate_id,
        updates={
            "current_stage": STAGE_SCORING,
            "status": "completed",
            "engaged": True,
        },
    )

    state["scoring_completed"] = True
    state["stage"] = STAGE_SCORING
    state["previous_stage"] = STAGE_MODEL_EXPLANATION
    state["stage_changed"] = True
    state["next_question"] = None

    state["ai_response"] = state.get(
        "ai_response",
        "",
    )

    state["last_ai_message"] = state.get(
        "last_ai_message",
        state.get(
            "ai_response",
            "",
        ),
    )

    state.setdefault(
        "system_notes",
        [],
    ).append(
        "Stage 5 candidate/interview data persisted to Supabase."
    )

    return state

# ============================================================================
# RESPONSE NODE
# ============================================================================

def response_node(
    state: AgentState,
) -> AgentState:

    state = deepcopy(state)

    candidate = (
        state.get(
            "candidate",
            {},
        )
        or {}
    )

    language = (
        state.get(
            "language",
            "english",
        )
        or "english"
    )

    current_stage = int(
        state.get(
            "stage",
            STAGE_INITIAL,
        )
        or STAGE_INITIAL
    )

    # ------------------------------------------------------------------------
    # Stage 5 final response
    # ------------------------------------------------------------------------

    if current_stage == STAGE_SCORING:

        response = state.get(
            "ai_response",
            "",
        )

        if not isinstance(
            response,
            str,
        ):
            response = ""

        if not response.strip():

            if language == "roman_urdu":

                response = (
                    "Shukriya. Aap ka assessment complete "
                    "ho gaya hai."
                )

            elif language == "urdu":

                response = (
                    "شکریہ! آپ کا assessment مکمل ہو گیا ہے۔"
                )

            else:

                response = (
                    "Thank you. Your assessment is complete."
                )

        state["ai_response"] = response
        state["last_ai_message"] = response

        return state

    missing_fields = get_missing_basic_fields(
        candidate
    )

    # ------------------------------------------------------------------------
    # Stage 0 / 1
    # ------------------------------------------------------------------------

    if (
        current_stage <= STAGE_BASIC
        and missing_fields
    ):

        response = generate_next_basic_question(
            candidate=candidate,
            language=language,
        )

        state["next_question"] = response

    # ------------------------------------------------------------------------
    # Stage 2
    # ------------------------------------------------------------------------

    elif current_stage == STAGE_MATERIALS:

        response = state.get(
            "next_question"
        )

        if (
            not isinstance(
                response,
                str,
            )
            or not response.strip()
        ):

            response = _materials_invitation(
                language
            )

        state["next_question"] = response

    # ------------------------------------------------------------------------
    # Stage 4
    # ------------------------------------------------------------------------

    elif current_stage == STAGE_MODEL_EXPLANATION:

        response = state.get(
            "model_explanation",
            "",
        )

        if (
            not isinstance(
                response,
                str,
            )
            or not response.strip()
        ):

            if language == "roman_urdu":

                response = (
                    "Aap ka interview complete ho gaya hai. "
                    "Ab main aap ko Talent Live ka model "
                    "samjhata hoon."
                )

            elif language == "urdu":

                response = (
                    "آپ کا انٹرویو مکمل ہو گیا ہے۔ "
                    "اب میں آپ کو Talent Live کا model "
                    "سمجھاتا ہوں۔"
)

            else:

                response = (
                    "Your interview is complete. "
                    "Let me explain how the Talent Live model works."
                )

        state["model_explanation"] = response
        state["next_question"] = None

    # ------------------------------------------------------------------------
    # Stage 3 Interview
    # ------------------------------------------------------------------------

    elif current_stage == STAGE_INTERVIEW:

        interview_question = state.get(
            "next_question"
        )

        if (
            isinstance(
                interview_question,
                str,
            )
            and interview_question.strip()
        ):

            response = (
                interview_question.strip()
            )

        else:

            response = (
                _fallback_interview_question(
                    language
                )
            )

            state["next_question"] = response

        # --------------------------------------------------------------------
        # CRITICAL:
        #
        # Whatever response is actually sent to the candidate becomes the
        # active question for the NEXT candidate message.
        # --------------------------------------------------------------------

        _snapshot_active_interview_question(
            state
        )

    # ------------------------------------------------------------------------
    # Safety fallback
    # ------------------------------------------------------------------------

    else:

        if language == "english":

            response = (
                "Thank you. Let's continue."
            )

        elif language == "roman_urdu":

            response = (
                "Shukriya. Chaliye continue karte hain."
            )

        else:

            response = (
                "شکریہ! آئیے آگے بڑھتے ہیں۔"
            )

    state["ai_response"] = response
    state["last_ai_message"] = response

    # =========================================================================
    # CONVERSATION HISTORY
    # =========================================================================

    history = state.setdefault(
        "conversation_history",
        [],
    )

    user_message = (
        state.get(
            "last_user_message",
            state.get(
                "message",
                "",
            ),
        )
        or ""
    )

    user_message = str(
        user_message
    )

    append_user = True

    if history:

        last_item = history[-1]

        if (
            isinstance(
                last_item,
                dict,
            )
            and last_item.get(
                "role"
            ) == "user"
            and last_item.get(
                "content"
            ) == user_message
        ):

            append_user = False

    if (
        append_user
        and user_message.strip()
    ):

        history.append(
            {
                "role": "user",
                "content": user_message,
            }
        )

    append_assistant = True

    if history:

        last_item = history[-1]

        if (
            isinstance(
                last_item,
                dict,
            )
            and last_item.get(
                "role"
            ) == "assistant"
            and last_item.get(
                "content"
            ) == response
        ):

            append_assistant = False

    if append_assistant:

        history.append(
            {
                "role": "assistant",
                "content": response,
            }
        )

    return state

# ============================================================================
# ============================================================================
# GRAPH ROUTING
# ============================================================================

def _route_after_materials(
    state: AgentState,
) -> str:

    stage = int(
        state.get(
            "stage",
            STAGE_INITIAL,
        )
        or STAGE_INITIAL
    )

    if stage >= STAGE_INTERVIEW:
        return "interview"

    return "response"


def _route_after_interview(
    state: AgentState,
) -> str:

    if state.get(
        "interview_complete",
        False,
    ):
        return "model_explanation"

    return "response"


def _route_after_response(
    state: AgentState,
) -> str:

    stage = int(
        state.get(
            "stage",
            STAGE_INITIAL,
        )
        or STAGE_INITIAL
    )

    if stage == STAGE_MODEL_EXPLANATION:
        return "scoring"

    return "end"


def _local_extract_candidate(
    message: str,
    existing: Dict[str, Any] | None = None,
    expected_field: str | None = None,
) -> Dict[str, Any]:

    extracted: Dict[str, Any] = {}

    message = str(message or "").strip()

    if not message:
        return extracted

    existing = existing or {}

    # ============================================================
    # FIELD-AWARE EXTRACTION
    # ============================================================
    # If Stage 1 is currently asking for a specific field,
    # interpret a short/direct answer according to that field.
    # This is critical for answers such as:
    #   "25"              -> age
    #   "Bahawalnagar"    -> location
    #   "3 years"         -> experience
    # ============================================================

    if expected_field == "name":
        name = _extract_name(message)

        if name:
            extracted["name"] = name
        else:
            cleaned = message.strip(" .,!?")

            if cleaned and len(cleaned.split()) <= 5:
                extracted["name"] = cleaned

    elif expected_field == "age":
        age = _extract_age(message)

        if age is not None:
            extracted["age"] = age
        else:
            match = re.fullmatch(
                r"\s*(\d{1,3})\s*",
                message,
            )

            if match:
                age = int(match.group(1))

                if 10 <= age <= 100:
                    extracted["age"] = age

    elif expected_field == "location":
        location = _extract_location(message)

        if location:
            extracted["location"] = location
        else:
            cleaned = message.strip(" .,!?")

            if cleaned and len(cleaned.split()) <= 6:
                extracted["location"] = cleaned

    elif expected_field == "experience":
        experience = _extract_experience(message)

        if experience:
            extracted["experience"] = experience
        else:
            match = re.fullmatch(
                r"\s*(\d+(?:\.\d+)?)\s*(?:years?|yrs?)\s*",
                message,
                re.IGNORECASE,
            )

            if match:
                extracted["experience"] = (
                    f"{match.group(1)} years"
                )

    # ============================================================
    # NORMAL EXTRACTION
    # ============================================================

    name = _extract_name(message)

    if name and "name" not in extracted:
        extracted["name"] = name

    age = _extract_age(message)

    if age is not None and "age" not in extracted:
        extracted["age"] = age

    location = _extract_location(message)

    if location and "location" not in extracted:
        extracted["location"] = location

    experience = _extract_experience(message)

    if experience and "experience" not in extracted:
        extracted["experience"] = experience

    lower = message.lower()

    # ============================================================
    # CURRENT JOB
    # ============================================================

    job_patterns = [
        r"\bi work in\s+(.+)",
        r"\bi work as\s+(.+)",
        r"\bcurrently work in\s+(.+)",
        r"\bcurrently work as\s+(.+)",
        r"\bworking in\s+(.+)",
        r"\bworking as\s+(.+)",
    ]

    for pattern in job_patterns:

        match = re.search(
            pattern,
            message,
            re.IGNORECASE,
        )

        if match:

            value = match.group(1).strip()

            value = re.split(
                r"[.!?\n]",
                value,
            )[0].strip()

            if value:
                extracted["current_job"] = value
                break

    # ============================================================
    # SKILLS
    # ============================================================

    skill_terms = [
        "sales",
        "marketing",
        "coding",
        "programming",
        "python",
        "javascript",
        "shopify",
        "automation",
        "ai",
        "design",
        "graphic design",
        "video editing",
        "customer service",
        "management",
    ]

    found_skills = []

    for skill in skill_terms:

        # Avoid matching "ai" inside unrelated words.
        if skill == "ai":
            if re.search(
                r"\bai\b",
                lower,
            ):
                found_skills.append(skill)

        elif skill in lower:
            found_skills.append(skill)

    if found_skills:
        extracted["skills"] = found_skills

    # ============================================================
    # EDUCATION
    # ============================================================

    education_patterns = [
        r"\bi studied\s+(.+)",
        r"\bstudied\s+(.+)",
        r"\beducation\s*:\s*(.+)",
        r"\bdegree\s*:\s*(.+)",
    ]

    for pattern in education_patterns:

        match = re.search(
            pattern,
            message,
            re.IGNORECASE,
        )

        if match:

            value = match.group(1).strip()

            value = re.split(
                r"[.!?\n]",
                value,
            )[0].strip()

            if value:
                extracted["education"] = value
                break

    return extracted



# GRAPH BUILDER
# ============================================================================

def build_talent_live_graph():

    builder = StateGraph(
        AgentState
    )

    builder.add_node(
        "candidate_extraction",
        candidate_extraction_node,
    )

    builder.add_node(
        "materials",
        materials_stage_node,
    )

    builder.add_node(
        "interview",
        interview_stage_node,
    )

    builder.add_node(
        "model_explanation",
        model_explanation_stage_node,
    )

    builder.add_node(
        "response",
        response_node,
    )

    builder.add_node(
        "scoring",
        scoring_stage_node,
    )

    builder.add_edge(
        START,
        "candidate_extraction",
    )

    builder.add_edge(
        "candidate_extraction",
        "materials",
    )

    builder.add_conditional_edges(
        "materials",
        _route_after_materials,
        {
            "response": "response",
            "interview": "interview",
        },
    )

    builder.add_conditional_edges(
        "interview",
        _route_after_interview,
        {
            "model_explanation": "model_explanation",
            "response": "response",
        },
    )

    builder.add_edge(
        "model_explanation",
        "response",
    )

    builder.add_conditional_edges(
        "response",
        _route_after_response,
        {
            "scoring": "scoring",
            "end": END,
        },
    )

    builder.add_edge(
        "scoring",
        END,
    )

    return builder.compile()


# ============================================================================
# COMPILED GRAPH
# ============================================================================

talent_live_graph = (
    build_talent_live_graph()
)

# ============================================================================
# PUBLIC RUNNER
# ============================================================================

def run_agent(
    state: AgentState,
) -> AgentState:

    current_stage = int(
        state.get(
            "stage",
            STAGE_INITIAL,
        )
        or STAGE_INITIAL
    )

    if (
        current_stage == STAGE_SCORING
        and state.get(
            "scoring_completed"
        ) is True
    ):

        return deepcopy(
            state
        )

    working_state = deepcopy(
        state
    )

    result = talent_live_graph.invoke(
        working_state
    )

    return result

# ========================================================================
# SINGLE MESSAGE RUNNER
# ========================================================================

def run_agent_message(
    candidate_id: str,
    phone_number: str,
    message: str,
) -> AgentState:

    from app.agents.state import (
        create_initial_state
    )

    state = create_initial_state(
        candidate_id=candidate_id,
        phone_number=phone_number,
    )

    state["message"] = message

    return run_agent(
        state
    )


def run_conversation(
    candidate_id: str,
    phone_number: str,
    messages: List[str],
) -> AgentState:

    from app.agents.state import (
        create_initial_state
    )

    state = create_initial_state(
        candidate_id=candidate_id,
        phone_number=phone_number,
    )

    for message in messages:

        state["message"] = message

        state = run_agent(
            state
        )

    return state


# ============================================================
# DEBUG / TEST HELPERS
# ============================================================

def print_interview_status(
    state: Dict[str, Any],
) -> None:
    """
    Print interview status for local testing.
    """

    status = get_interview_status(
        state
    )

    print("=" * 60)
    print("TALENT LIVE INTERVIEW STATUS")
    print("=" * 60)

    print(
        f"Stage: {status['stage']}"
    )

    print(
        f"Language: {status['language']}"
    )

    print(
        f"Category: {status['current_category']}"
    )

    print(
        f"Current question: "
        f"{status['current_question']}"
    )

    print(
        f"Pending category: "
        f"{status['pending_category']}"
    )

    print(
        f"Pending question: "
        f"{status['pending_question']}"
    )

    print(
        f"Questions asked: "
        f"{status['questions_asked']}"
    )

    print(
        f"Answers recorded: "
        f"{status['answers_recorded']}"
    )

    print(
        f"Vague probe used: "
        f"{status['vague_probe_used']}"
    )

    print(
        f"Probe categories: "
        f"{status['probe_categories']}"
    )

    print(
        f"Interview complete: "
        f"{status['interview_complete']}"
    )

    print(
        f"Next question: "
        f"{status['next_question']}"
    )

    print("=" * 60)


# ============================================================
# LOCAL TEST
# ============================================================

if __name__ == "__main__":

    test_state = {
        "stage": STAGE_INTERVIEW,

        "language": "english",

        "candidate": {
            "name": "Ali",
            "phone_number": "+923000000000",
            "age": 25,
            "location": "Lahore",
            "experience": "3 years experience",

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
        },

        "interview": {
            "current_category": None,
            "current_question": None,

            # ------------------------------------------------
            # NEW AUTHORITATIVE QUESTION CONTEXT
            # ------------------------------------------------

            "pending_category": None,
            "pending_question": None,

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
        },

        "next_question": None,
        "interview_started": False,
        "interview_complete": False,
    }

    print("=" * 70)
    print("TALENT LIVE INTERVIEW ENGINE TEST")
    print("=" * 70)

    # ========================================================
    # QUESTION 1
    # ========================================================

    question = get_next_interview_question(
        test_state
    )

    print("\nQUESTION 1:")
    print(question)

    print("\nPENDING CONTEXT:")
    print(
        "Category:",
        test_state["interview"]["pending_category"],
    )
    print(
        "Question:",
        test_state["interview"]["pending_question"],
    )

    print("\nRECORDED QUESTIONS:")
    print(
        test_state["interview"]["questions_asked"]
    )

    # ========================================================
    # VAGUE ANSWER
    # ========================================================

    process_answer(
        test_state,
        "Sales",
    )

    print("\nANSWER 1 RECORDED:")
    print(
        test_state["interview"]["answers"][-1]
    )

    print("\nPROBE GENERATED:")
    print(
        test_state.get("next_question")
    )

    # ========================================================
    # INTERVIEW NODE PRESERVES PROBE
    # ========================================================

    question = interview_node(
        test_state
    ).get("next_question")

    print("\nQUESTION 2 / PROBE:")
    print(question)

    print("\nPENDING CONTEXT:")
    print(
        "Category:",
        test_state["interview"]["pending_category"],
    )
    print(
        "Question:",
        test_state["interview"]["pending_question"],
    )

    print("\nRECORDED QUESTIONS:")
    print(
        test_state["interview"]["questions_asked"]
    )

    # ========================================================
    # ANSWER PROBE
    # ========================================================

    process_answer(
        test_state,
        (
            "I worked with customers and helped them "
            "choose the right products."
        ),
    )

    print("\nANSWER 2 RECORDED:")
    print(
        test_state["interview"]["answers"][-1]
    )

    # ========================================================
    # GENERATE NEXT NORMAL QUESTION
    # ========================================================

    question = interview_node(
        test_state
    ).get("next_question")

    print("\nQUESTION 3:")
    print(question)

    print("\nPENDING CONTEXT:")
    print(
        "Category:",
        test_state["interview"]["pending_category"],
    )
    print(
        "Question:",
        test_state["interview"]["pending_question"],
    )

    print("\nRECORDED QUESTIONS:")
    print(
        test_state["interview"]["questions_asked"]
    )

    # ========================================================
    # STATUS
    # ========================================================

    print_interview_status(
        test_state
    )

    # ========================================================
    # ALL ANSWERS
    # ========================================================

    print("\nALL RECORDED ANSWERS:")

    for index, answer in enumerate(
        test_state["interview"]["answers"],
        start=1,
    ):

        print(
            f"{index}. "
            f"[{answer['category']}] "
            f"Q: {answer['question']}"
        )

        print(
            f"   A: {answer['answer']}"
        )

    print("\nFINAL INTERVIEW STATE:")
    print(
        test_state["interview"]
    )

    print("\nTEST COMPLETE")


