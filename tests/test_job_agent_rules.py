import asyncio
import os
import unittest
from datetime import UTC, datetime
from unittest.mock import patch

from ai_engine import JobMatchEvaluation
from job_scraper import JobListing, JobSearchResult
from matching_pipeline import run_user_job_search


PROFILE = {
    "whatsapp_number": "918790431602",
    "target_title": "Software Development Engineer, Backend Engineer",
    "experience_summary": "Python Java Spring Boot REST APIs Docker Kubernetes AWS SQL",
    "resume_text": "Python Java Spring Boot REST APIs Docker Kubernetes AWS SQL microservices",
}


def make_job(index: int) -> JobListing:
    return JobListing(
        job_id=f"official:test:{index}",
        title=f"Software Development Engineer {index}",
        company="Amazon" if index % 2 == 0 else "Microsoft",
        location="Bengaluru, India",
        description="Python Java backend REST APIs SQL Docker Kubernetes AWS 1+ years",
        url=f"https://example.com/jobs/{index}",
        source="official_test",
        posted_at=datetime.now(UTC),
    )


def make_search_result(count: int) -> JobSearchResult:
    return JobSearchResult(
        query="software engineer",
        location="India",
        source_count=1,
        job_count=count,
        jobs=[make_job(index) for index in range(count)],
    )


def make_evaluator(score: int):
    def evaluate(**_: object) -> JobMatchEvaluation:
        return JobMatchEvaluation(
            match_percentage=score,
            matched_skills=["Python", "Java", "REST APIs"],
            missing_skills=[],
            short_reason="Test score",
            should_alert=score >= 75,
        )

    return evaluate


class JobAgentMatchingRulesTest(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["MIN_MATCH_SCORE"] = "75"
        os.environ["MAX_MATCHED_JOBS_PER_USER"] = "0"
        os.environ["ALLOW_BELOW_THRESHOLD_FILL"] = "false"
        os.environ["SEND_ALL_ABOVE_THRESHOLD_MATCHES"] = "true"
        os.environ["JOB_EVALUATION_POOL_LIMIT"] = "0"

    def run_search(self, *, job_count: int, score: int, limit: int = 15):
        async def fake_fetch_jobs(**_: object) -> JobSearchResult:
            return make_search_result(job_count)

        with (
            patch("matching_pipeline.get_user_profile", return_value=PROFILE),
            patch("matching_pipeline.fetch_jobs", side_effect=fake_fetch_jobs),
            patch("matching_pipeline.get_sent_job_ids", return_value=set()),
            patch("matching_pipeline.evaluate_job_match", side_effect=make_evaluator(score)),
            patch("matching_pipeline.generate_tailored_resume_txt", return_value=None),
        ):
            return asyncio.run(
                run_user_job_search(
                    whatsapp_number="918790431602",
                    limit=limit,
                    threshold=75,
                    dry_run=True,
                    preferred_filters=True,
                    recent_days=1,
                    max_evaluations=0,
                    max_matched_jobs_per_user=0,
                )
            )

    def test_score_74_is_excluded(self) -> None:
        result = self.run_search(job_count=1, score=74)
        self.assertEqual(result.alert_count, 0)

    def test_score_75_is_included(self) -> None:
        result = self.run_search(job_count=1, score=75)
        self.assertEqual(result.alert_count, 1)

    def test_score_100_is_included(self) -> None:
        result = self.run_search(job_count=1, score=100)
        self.assertEqual(result.alert_count, 1)

    def test_15_qualifying_jobs_returns_all_15(self) -> None:
        result = self.run_search(job_count=15, score=75)
        self.assertEqual(result.alert_count, 15)

    def test_16_qualifying_jobs_returns_all_16(self) -> None:
        result = self.run_search(job_count=16, score=75)
        self.assertEqual(result.alert_count, 16)

    def test_25_qualifying_jobs_returns_all_25(self) -> None:
        result = self.run_search(job_count=25, score=75)
        self.assertEqual(result.alert_count, 25)

    def test_26_qualifying_jobs_returns_all_26(self) -> None:
        result = self.run_search(job_count=26, score=75)
        self.assertEqual(result.alert_count, 26)

    def test_100_qualifying_jobs_returns_all_100(self) -> None:
        result = self.run_search(job_count=100, score=75)
        self.assertEqual(result.alert_count, 100)

    def test_limit_one_does_not_limit_jobs_for_profile(self) -> None:
        result = self.run_search(job_count=16, score=75, limit=1)
        self.assertEqual(result.alert_count, 16)


if __name__ == "__main__":
    unittest.main()
