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

from typing import Any, Dict, List, Optional


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

    # NOTE: internally still called "family" (category key + evidence field
    # name), but the questions were reworded away from personal-family
    # topics (father's job, siblings, living arrangement) to professional
    # availability/work-stability topics. See CATEGORY_REQUIRED_FIELDS
    # below for the same legacy-naming note on the underlying field names.
    "family": {
        "english": [
            "What does your weekly availability look like — roughly how "
            "many hours could you commit to this kind of work?",
            "Do you have any other ongoing commitments, like studies or "
            "another job, that we should factor into your availability?",
            "Is your current setup — where you live and work from — "
            "something you expect to stay stable for the next several "
            "months?",
            "Do you have a reliable internet connection and a quiet "
            "space to work from consistently?",
        ],
        "urdu": [
            "آپ کی ہفتہ وار availability کیسی ہے — تقریباً کتنے گھنٹے آپ "
            "اس قسم کے کام کے لیے دے سکتے ہیں؟",
            "کیا آپ کے کوئی اور ongoing commitments ہیں، جیسے پڑھائی یا "
            "کوئی اور job، جو ہمیں آپ کی availability سوچتے وقت ذہن میں "
            "رکھنی چاہیے؟",
            "کیا آپ کا موجودہ setup — جہاں آپ رہتے اور کام کرتے ہیں — "
            "اگلے چند مہینوں تک stable رہے گا؟",
            "کیا آپ کے پاس reliable انٹرنیٹ کنکشن اور ایک پرسکون جگہ ہے "
            "جہاں آپ مستقل طور پر کام کر سکیں؟",
        ],
        "roman_urdu": [
            "Aap ki weekly availability kaisi hai — takhmeenan kitne "
            "hours aap is tarah ke kaam ke liye de sakte hain?",
            "Kya aap ke koi aur ongoing commitments hain, jaise parhai "
            "ya koi aur job, jo hume aapki availability sochte waqt "
            "dhyan mein rakhni chahiye?",
            "Kya aapka current setup — jahan aap rehte aur kaam karte "
            "hain — agle kuch mahinon tak stable rahega?",
            "Kya aap ke paas reliable internet connection aur ek quiet "
            "jagah hai jahan aap consistently kaam kar sakein?",
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
    # These field names are legacy from the original personal-family
    # questions and are effectively inert now (nothing extracts free-text
    # answers into these specific candidate dict keys) - the actual
    # answers are captured in interview["family_evidence"] regardless.
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
# ANSWER PROCESSING
# ============================================================

def process_answer(
    state: Dict[str, Any],
    answer: str,
) -> Dict[str, Any]:
    """
    Process exactly one candidate answer.

    Flow:

        pending question
              |
              v
        capture question/category
              |
              v
        record answer
              |
              v
        vague?
          /       \
        YES       NO
         |         |
         v         v
       probe     advance
         |         |
         v         v
      next Q    next Q generated later

    IMPORTANT:
    The answer is associated with the pending question BEFORE
    any category advancement takes place.
    """

    ensure_interview_structure(state)

    # --------------------------------------------------------
    # Only process answers during Stage 3
    # --------------------------------------------------------

    if state.get("stage") != STAGE_INTERVIEW:
        return state

    # --------------------------------------------------------
    # Validate answer
    # --------------------------------------------------------

    if answer is None:
        return state

    answer = str(answer).strip()

    if not answer:
        return state

    interview = state["interview"]

    # --------------------------------------------------------
    # CAPTURE THE EXACT PENDING QUESTION FIRST
    # --------------------------------------------------------

    pending_category = interview.get(
        "pending_category"
    )

    pending_question = interview.get(
        "pending_question"
    )

    # --------------------------------------------------------
    # Backward-compatible fallback for older state
    # --------------------------------------------------------

    if not pending_category:
        pending_category = interview.get(
            "current_category"
        )

    if not pending_question:
        pending_question = interview.get(
            "current_question"
        )

    # --------------------------------------------------------
    # No active question = do not attach answer randomly
    # --------------------------------------------------------

    if not pending_category:
        return state

    if not pending_question:
        return state

    # --------------------------------------------------------
    # RECORD ANSWER AGAINST EXACT PENDING QUESTION
    # --------------------------------------------------------

    mark_answer(
        state,
        answer,
        pending_category,
    )

    # --------------------------------------------------------
    # VAGUE ANSWER
    # --------------------------------------------------------

    if is_vague_answer(answer):

        # mark_answer() clears pending context after recording.
        # Restore the category temporarily so the probe stays
        # inside the same interview category.

        interview["current_category"] = (
            pending_category
        )

        probe = handle_vague_answer(
            state
        )

        if probe:

            state["next_question"] = probe

            return state

    # --------------------------------------------------------
    # NORMAL ADVANCEMENT
    # --------------------------------------------------------

    interview["current_category"] = (
        pending_category
    )

    advance_after_answer(
        state
    )

    # --------------------------------------------------------
    # IMPORTANT:
    #
    # Do not generate another question here.
    #
    # interview_node() will generate the next question.
    # --------------------------------------------------------

    state["next_question"] = None

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

        return None

    state["next_question"] = question

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