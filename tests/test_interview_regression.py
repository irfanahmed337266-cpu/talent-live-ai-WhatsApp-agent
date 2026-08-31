import unittest

from app.agents.interview import (
    get_next_interview_question,
    process_answer,
    interview_node,
)
from app.agents.state import create_initial_state


class InterviewRepeatRegressionTest(unittest.TestCase):
    def setUp(self):
        self.state = create_initial_state()
        self.state["stage"] = 3
        self.state["language"] = "english"
        self.state["interview"] = {
            "current_category": None,
            "current_question": None,
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
        }

    def test_answer_does_not_repeat_same_question(self):
        first_question = get_next_interview_question(self.state)
        self.assertIsInstance(first_question, str)
        self.assertTrue(first_question.strip())

        process_answer(self.state, "I am a software engineer.")

        self.assertEqual(len(self.state["interview"]["answers"]), 1)
        self.assertIsNone(self.state.get("next_question"))
        self.assertIsNone(self.state["interview"].get("pending_question"))

        second_question = interview_node(self.state).get("next_question")
        self.assertIsInstance(second_question, str)
        self.assertTrue(second_question.strip())
        self.assertNotEqual(second_question, first_question)


if __name__ == "__main__":
    unittest.main()
