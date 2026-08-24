"""
Talent Live - Simple AI Agent

ONE GEMINI CALL PER USER MESSAGE

Flow:
    User message
        ↓
    ONE Gemini call
        ↓
    Extract candidate fields
    Generate AI response
    Decide next stage/question
        ↓
    Updated state

This file is intentionally simple for incremental testing.

It does NOT:
- use Gemini automatic function calling
- make separate extraction + response calls
- modify the old graph/state/interview files
- require CV/GitHub uploads

Candidate fields:
- name
- phone_number
- age
- location
- experience
- current_job
- skills
- work_history
- education
- father_occupation
- brothers
- living_situation
- housing_status
- background
- additional_information
"""

import json
import os
from typing import Any, Dict, List

from dotenv import load_dotenv
from google import genai
from google.genai import types


# ============================================================
# ENVIRONMENT
# ============================================================

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not GEMINI_API_KEY:
    raise RuntimeError(
        "GEMINI_API_KEY was not found in the .env file."
    )


# ============================================================
# GEMINI CLIENT
# ============================================================

client = genai.Client(
    api_key=GEMINI_API_KEY
)

MODEL_NAME = "gemini-2.5-flash"


# ============================================================
# INITIAL CANDIDATE
# ============================================================

EMPTY_CANDIDATE: Dict[str, Any] = {
    "name": None,
    "phone_number": "+923000000000",
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


# ============================================================
# STATE HELPERS
# ============================================================

def create_initial_state() -> Dict[str, Any]:
    """
    Create a fresh candidate interview state.
    """

    return {
        "stage": 1,
        "question_count": 0,
        "candidate": dict(EMPTY_CANDIDATE),
        "conversation": [],
        "finished": False,
    }


def clean_json_response(text: str) -> Dict[str, Any]:
    """
    Safely convert Gemini response into a Python dictionary.

    Handles:
    - normal JSON
    - JSON wrapped in ```json ... ```
    - accidental surrounding text
    """

    if not text:
        return {}

    text = text.strip()

    # Remove markdown JSON fences
    if text.startswith("```json"):
        text = text[7:]

    elif text.startswith("```"):
        text = text[3:]

    if text.endswith("```"):
        text = text[:-3]

    text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try extracting the first JSON object
    start = text.find("{")
    end = text.rfind("}")

    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(
                text[start:end + 1]
            )
        except json.JSONDecodeError:
            return {}

    return {}


# ============================================================
# CANDIDATE MERGE
# ============================================================

def merge_candidate(
    old_candidate: Dict[str, Any],
    new_candidate: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Safely merge newly extracted information.

    Gemini must never erase existing information simply because
    a field was not mentioned in the latest message.
    """

    merged = dict(old_candidate)

    for field in EMPTY_CANDIDATE.keys():

        if field not in new_candidate:
            continue

        new_value = new_candidate.get(field)

        # Do not overwrite existing information with null.
        if new_value is None:
            continue

        # Handle list fields
        if field in {"skills", "work_history"}:

            if not isinstance(new_value, list):
                continue

            existing = merged.get(field) or []

            if not isinstance(existing, list):
                existing = []

            combined = existing + new_value

            # Remove duplicates while preserving order
            cleaned = []

            for item in combined:
                if item is None:
                    continue

                item = str(item).strip()

                if not item:
                    continue

                if item not in cleaned:
                    cleaned.append(item)

            merged[field] = cleaned

        else:
            merged[field] = new_value

    return merged


# ============================================================
# INTERVIEW PROMPT
# ============================================================

SYSTEM_PROMPT = """
You are the Talent Live AI candidate screening assistant.

Your job is to interview a candidate naturally and collect their
candidate profile.

IMPORTANT:
You MUST return ONLY valid JSON.

Do NOT return markdown.
Do NOT return ```json.
Do NOT return explanations outside JSON.

You receive:
1. Current candidate information
2. Previous conversation
3. The latest candidate message

You must perform ALL of these tasks in ONE Gemini call:

A. Extract any new candidate information from the latest message.

B. Decide the next interview question.

C. Generate a natural, friendly AI response.

D. Decide the current interview stage.

--------------------------------------------------
CANDIDATE FIELDS
--------------------------------------------------

The candidate object contains:

name
phone_number
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

--------------------------------------------------
EXTRACTION RULES
--------------------------------------------------

Only extract information actually provided by the candidate.

NEVER invent information.

If a field was not mentioned in the latest message,
return null for that field.

For skills:
return a list of skills explicitly stated or clearly demonstrated.

For work_history:
return a list of concise factual descriptions of work experience
provided by the candidate.

For brothers:
if the candidate says "two brothers", return 2.

For age:
return a number.

For example:

"I am 25 years old"

must produce:

"age": 25

"I live with my family"

must produce:

"living_situation": "Lives with family"

"My father works in business"

must produce:

"father_occupation": "Business"

--------------------------------------------------
INTERVIEW FLOW
--------------------------------------------------

Stage 1:
Basic information.

Collect:
- name
- age
- location
- experience

Stage 2:
Optional CV/GitHub/portfolio/material discussion.

The candidate may NOT have a CV or GitHub.

Never force them to provide one.

Stage 3:
Interview.

Explore:
- skills
- current job
- work history
- difficult situations
- achievements
- education
- family/background
- future goals

Stage 4:
Finished.

Do not ask endless questions.

After sufficient information has been collected, finish
the interview.

--------------------------------------------------
QUESTION RULES
--------------------------------------------------

Ask ONLY ONE question at a time.

Do not ask multiple questions in one message.

Do not repeat a question when the candidate has already
provided the answer.

If the latest candidate message already answers the likely
next question, move forward.

Questions should feel natural rather than like a rigid form.

--------------------------------------------------
LANGUAGE
--------------------------------------------------

Respond in the candidate's language.

If the candidate uses English, respond in English.

If the candidate uses Urdu/Roman Urdu, respond naturally
in Urdu/Roman Urdu.

--------------------------------------------------
RESPONSE STYLE
--------------------------------------------------

Be:
- friendly
- professional
- concise
- conversational

Do not say:
"According to your profile..."

Do not expose internal stages.

Do not expose JSON.

Do not discuss scoring.

Do not tell the candidate whether they passed or failed.

--------------------------------------------------
OUTPUT FORMAT
--------------------------------------------------

Return exactly this JSON structure:

{
  "candidate_update": {
    "name": null,
    "phone_number": null,
    "age": null,
    "location": null,
    "experience": null,
    "current_job": null,
    "skills": [],
    "work_history": [],
    "education": null,
    "father_occupation": null,
    "brothers": null,
    "living_situation": null,
    "housing_status": null,
    "background": null,
    "additional_information": null
  },

  "stage": 3,

  "question_count_increment": 1,

  "next_question": "The next question here",

  "response": "Natural response to the candidate",

  "finished": false
}

IMPORTANT:
question_count_increment must normally be 1 when a new
interview question is being asked.

If you are simply acknowledging information without asking
a question, use 0.

If finished is true:
- next_question must be null
- response should politely close the conversation.
"""


# ============================================================
# ONE GEMINI CALL
# ============================================================

def call_gemini_once(
    candidate: Dict[str, Any],
    conversation: List[Dict[str, str]],
    user_message: str,
    question_count: int,
) -> Dict[str, Any]:
    """
    ONE and ONLY ONE Gemini request.

    This call handles:
    - extraction
    - stage decision
    - next question
    - response generation
    """

    conversation_text = ""

    for item in conversation[-12:]:
        role = item.get("role", "")
        content = item.get("content", "")

        conversation_text += (
            f"{role.upper()}: {content}\n"
        )

    prompt = f"""
{SYSTEM_PROMPT}

==================================================
CURRENT CANDIDATE
==================================================

{json.dumps(
    candidate,
    ensure_ascii=False,
    indent=2,
)}

==================================================
CURRENT QUESTION COUNT
==================================================

{question_count}

==================================================
PREVIOUS CONVERSATION
==================================================

{conversation_text}

==================================================
LATEST CANDIDATE MESSAGE
==================================================

{user_message}

==================================================
TASK
==================================================

Process the latest candidate message.

Extract all newly provided information.

Do not erase existing information.

Generate ONE natural response.

Ask ONE next question only.

Return ONLY JSON.
"""

    try:
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.3,
                response_mime_type="application/json",
            ),
        )

        text = response.text or ""

        result = clean_json_response(text)

        if not result:
            print()
            print("[Gemini returned invalid JSON]")
            print(text)

            return {
                "candidate_update": {},
                "stage": 3,
                "question_count_increment": 0,
                "next_question": None,
                "response": (
                    "Thanks for sharing that. "
                    "Could you tell me a little more about your work experience?"
                ),
                "finished": False,
            }

        return result

    except Exception as exc:

        error_text = str(exc)

        print()
        print("[Gemini error]")
        print(error_text)
        print()

        # ----------------------------------------------------
        # IMPORTANT:
        # Do NOT make another Gemini call here.
        #
        # This preserves the ONE-CALL-PER-MESSAGE design.
        # ----------------------------------------------------

        if "429" in error_text or "RESOURCE_EXHAUSTED" in error_text:

            return {
                "candidate_update": {},
                "stage": 3,
                "question_count_increment": 0,
                "next_question": None,
                "response": (
                    "Thanks for sharing that. "
                    "I have recorded the information so far. "
                    "Please continue with your next detail."
                ),
                "finished": False,
            }

        return {
            "candidate_update": {},
            "stage": 3,
            "question_count_increment": 0,
            "next_question": None,
            "response": (
                "Thank you. Please continue telling me "
                "about your experience."
            ),
            "finished": False,
        }


# ============================================================
# PROCESS ONE MESSAGE
# ============================================================

def run_agent_message(
    state: Dict[str, Any],
    user_message: str,
) -> Dict[str, Any]:
    """
    Process exactly ONE candidate message.

    Exactly ONE Gemini call is made.
    """

    candidate = state.get(
        "candidate",
        dict(EMPTY_CANDIDATE),
    )

    conversation = state.get(
        "conversation",
        [],
    )

    question_count = state.get(
        "question_count",
        0,
    )

    # --------------------------------------------------------
    # Store user message
    # --------------------------------------------------------

    conversation.append(
        {
            "role": "user",
            "content": user_message,
        }
    )

    # --------------------------------------------------------
    # ONE GEMINI CALL
    # --------------------------------------------------------

    result = call_gemini_once(
        candidate=candidate,
        conversation=conversation,
        user_message=user_message,
        question_count=question_count,
    )

    # --------------------------------------------------------
    # Merge extracted candidate information
    # --------------------------------------------------------

    candidate_update = result.get(
        "candidate_update",
        {},
    )

    if not isinstance(candidate_update, dict):
        candidate_update = {}

    candidate = merge_candidate(
        candidate,
        candidate_update,
    )

    # --------------------------------------------------------
    # Stage
    # --------------------------------------------------------

    stage = result.get(
        "stage",
        state.get("stage", 1),
    )

    try:
        stage = int(stage)
    except (TypeError, ValueError):
        stage = state.get("stage", 1)

    # Keep stage within expected range
    stage = max(1, min(stage, 4))

    # --------------------------------------------------------
    # Question count
    # --------------------------------------------------------

    increment = result.get(
        "question_count_increment",
        0,
    )

    try:
        increment = int(increment)
    except (TypeError, ValueError):
        increment = 0

    increment = max(0, min(increment, 1))

    question_count += increment

    # --------------------------------------------------------
    # AI response
    # --------------------------------------------------------

    ai_response = result.get(
        "response",
        "",
    )

    if not isinstance(ai_response, str):
        ai_response = str(ai_response)

    ai_response = ai_response.strip()

    # --------------------------------------------------------
    # Finished
    # --------------------------------------------------------

    finished = bool(
        result.get(
            "finished",
            False,
        )
    )

    if stage == 4:
        finished = True

    # --------------------------------------------------------
    # Store AI message
    # --------------------------------------------------------

    if ai_response:
        conversation.append(
            {
                "role": "assistant",
                "content": ai_response,
            }
        )

    # --------------------------------------------------------
    # Updated state
    # --------------------------------------------------------

    state["candidate"] = candidate
    state["stage"] = stage
    state["question_count"] = question_count
    state["conversation"] = conversation
    state["finished"] = finished

    state["next_question"] = result.get(
        "next_question"
    )

    return state


# ============================================================
# RUN COMPLETE TEST CONVERSATION
# ============================================================

def run_agent() -> Dict[str, Any]:
    """
    Local test conversation.

    IMPORTANT:
    This sends one Gemini request per user message.

    If the Gemini free tier has reached its daily quota,
    Gemini will return 429. The program will NOT retry
    automatically and therefore will NOT generate additional
    requests.
    """

    state = create_initial_state()

    test_messages = [
        (
            "My name is Ali. I am 25 years old, "
            "I live in Lahore, and I have 3 years experience in sales."
        ),
        (
            "I don't have a CV or GitHub. "
            "I can just tell you about my work."
        ),
        (
            "I am good at sales and dealing with customers. "
            "I can convince customers and build good relationships."
        ),
        (
            "I currently work in sales at a rice business. "
            "I deal with customers, take orders and follow up with buyers."
        ),
        (
            "One difficult customer was not interested in buying, "
            "so I explained the product properly and eventually closed the sale."
        ),
        (
            "I studied business administration."
        ),
        (
            "I live with my family. My father works in business "
            "and I have two brothers."
        ),
    ]

    print("=" * 70)
    print("TALENT LIVE SIMPLE AI AGENT TEST")
    print("ONE GEMINI CALL PER MESSAGE")
    print("=" * 70)

    for index, message in enumerate(
        test_messages,
        start=1,
    ):

        print()
        print("-" * 70)
        print(
            f"USER {index}: {message}"
        )

        state = run_agent_message(
            state,
            message,
        )

        print()

        # Get last assistant response
        ai_message = ""

        for item in reversed(
            state.get("conversation", [])
        ):
            if item.get("role") == "assistant":
                ai_message = item.get(
                    "content",
                    "",
                )
                break

        print(
            "AI:",
            ai_message,
        )

        print()
        print(
            "STAGE:",
            state.get("stage"),
        )

        print(
            "QUESTION COUNT:",
            state.get("question_count"),
        )

        print()
        print("CANDIDATE:")

        print(
            json.dumps(
                state.get(
                    "candidate",
                    {},
                ),
                indent=2,
                ensure_ascii=False,
            )
        )

    print()
    print("=" * 70)
    print("TEST FINISHED")
    print("=" * 70)

    return state


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    run_agent()