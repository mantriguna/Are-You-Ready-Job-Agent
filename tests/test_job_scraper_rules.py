import asyncio
import unittest

from company_sources import CompanySource
from job_scraper import JobListing, _fetch_amazon_jobs, _fetch_generic_official_jobs, _is_india_job


class FakeResponse:
    def __init__(self, payload=None, text="", content_type="application/json"):
        self._payload = payload or {}
        self.text = text
        self.headers = {"content-type": content_type}

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self._payload


class FakeAmazonClient:
    def __init__(self):
        self.offsets: list[int] = []

    async def get(self, _url, *, params=None, headers=None):
        offset = int((params or {}).get("offset", 0))
        self.offsets.append(offset)
        if offset == 0:
            return FakeResponse(
                {
                    "jobs": [
                        {
                            "id": "A1",
                            "title": "Software Development Engineer I",
                            "normalized_location": "Bengaluru, KA, IND",
                            "description": "Java Python backend",
                            "job_path": "/en/jobs/A1/software-development-engineer-i",
                        },
                        {
                            "id": "A2",
                            "title": "Backend Engineer",
                            "normalized_location": "Hyderabad, TS, IND",
                            "description": "Spring Boot microservices",
                            "job_path": "/en/jobs/A2/backend-engineer",
                        },
                    ]
                }
            )
        if offset == 100:
            return FakeResponse(
                {
                    "jobs": [
                        {
                            "id": "A3",
                            "title": "Software Engineer II",
                            "normalized_location": "Chennai, TN, IND",
                            "description": "REST APIs SQL Docker",
                            "job_path": "/en/jobs/A3/software-engineer-ii",
                        }
                    ]
                }
            )
        return FakeResponse({"jobs": []})


class FakeHtmlClient:
    async def get(self, _url, *, headers=None):
        return FakeResponse(
            text="""
                <a href="https://evil.example/jobs/software-engineer">Software Engineer</a>
                <a href="/jobs/backend-engineer-india">Backend Engineer job India</a>
            """,
            content_type="text/html; charset=utf-8",
        )


class JobScraperRulesTest(unittest.TestCase):
    def test_amazon_pagination_collects_every_page(self) -> None:
        client = FakeAmazonClient()
        jobs = asyncio.run(_fetch_amazon_jobs(client, query="software engineer", limit=100))

        self.assertEqual([job.job_id for job in jobs], ["amazon:A1", "amazon:A2", "amazon:A3"])
        self.assertEqual(client.offsets, [0, 100, 200])

    def test_generic_official_parser_rejects_non_official_urls(self) -> None:
        source = CompanySource(
            company_name="ExampleCo",
            careers_url="https://careers.example.com/jobs",
            official_domains=["careers.example.com"],
        )
        jobs = asyncio.run(
            _fetch_generic_official_jobs(FakeHtmlClient(), source, query="backend engineer")
        )

        self.assertEqual(len(jobs), 1)
        self.assertEqual(str(jobs[0].url), "https://careers.example.com/jobs/backend-engineer-india")

    def test_india_filter_rejects_non_india_explicit_location(self) -> None:
        job = JobListing(
            job_id="greenhouse:postman:123",
            title="Account Development Representative",
            company="Postman",
            location="London, UK; Remote, UK",
            description="Global role with offices in India and the US.",
            url="https://job-boards.greenhouse.io/postman/jobs/123",
            source="greenhouse",
        )

        self.assertFalse(_is_india_job(job))

    def test_india_filter_does_not_match_indonesia(self) -> None:
        job = JobListing(
            job_id="greenhouse:agoda:123",
            title="Backend Software Engineer",
            company="Agoda",
            location="Bali, Indonesia",
            description="Backend platform role.",
            url="https://job-boards.greenhouse.io/agoda/jobs/123",
            source="greenhouse",
        )

        self.assertFalse(_is_india_job(job))


if __name__ == "__main__":
    unittest.main()
