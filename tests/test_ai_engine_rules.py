import os
import unittest
from unittest.mock import patch

from ai_engine import JobMatchEvaluation, evaluate_job_match


class FakeGeminiModels:
    def generate_content(self, **_):
        return type(
            "FakeGeminiResponse",
            (),
            {
                "parsed": JobMatchEvaluation(
                    match_percentage=100,
                    matched_skills=["Invented perfect fit"],
                    missing_skills=[],
                    short_reason="LLM-only score should not control final threshold.",
                    should_alert=True,
                )
            },
        )()


class FakeGeminiClient:
    models = FakeGeminiModels()


class AiEngineRulesTest(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["MIN_MATCH_SCORE"] = "75"
        os.environ["USE_LLM_MATCHING"] = "true"

    def tearDown(self) -> None:
        os.environ.pop("USE_LLM_MATCHING", None)

    def test_llm_output_does_not_override_deterministic_score(self) -> None:
        with patch("ai_engine.get_gemini_client", return_value=FakeGeminiClient()):
            result = evaluate_job_match(
                target_title="Software Development Engineer",
                experience_summary="Python Java REST APIs",
                resume_text="Python Java REST APIs",
                job_title="Marketing Operations Lead",
                job_description="Own sales campaigns, marketing operations, and finance reporting.",
            )

        self.assertLess(result.match_percentage, 75)
        self.assertFalse(result.should_alert)
        self.assertEqual(result.matched_skills, ["Invented perfect fit"])


if __name__ == "__main__":
    unittest.main()
