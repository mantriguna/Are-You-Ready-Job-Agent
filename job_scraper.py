import asyncio
import os
from datetime import UTC, datetime
from html import unescape
from re import findall, search, sub
from urllib.parse import quote

import httpx
from pydantic import BaseModel, Field, HttpUrl


class JobListing(BaseModel):
    job_id: str
    title: str
    company: str
    location: str | None = None
    description: str = ""
    url: HttpUrl
    source: str
    posted_at: datetime | None = None
    employment_type: str | None = None
    salary_text: str | None = None
    salary_confidence: str = "unknown"


class JobSearchResult(BaseModel):
    query: str | None = None
    location: str | None = None
    source_count: int
    job_count: int
    jobs: list[JobListing]


def _csv_env(name: str) -> list[str]:
    raw_value = os.getenv(name, "")
    return [item.strip() for item in raw_value.split(",") if item.strip()]


def _clean_html(value: str | None) -> str:
    if not value:
        return ""
    text = unescape(value)
    text = sub(r"<br\s*/?>", "\n", text, flags=2)
    text = sub(r"<[^>]+>", " ", text)
    text = unescape(text)
    return sub(r"\s+", " ", text).strip()


def _matches_filters(job: JobListing, query: str | None, location: str | None) -> bool:
    searchable_text = " ".join(
        part for part in [job.title, job.company, job.location, job.description] if part
    ).lower()

    if query and query.lower() not in searchable_text:
        return False

    if location and location.lower() == "india":
        if "india" not in searchable_text and ", ind" not in searchable_text:
            return False
    elif location and location.lower() not in searchable_text:
        return False

    return True


def _parse_amazon_posted_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%B %d, %Y").replace(tzinfo=UTC)
    except ValueError:
        return None


def _minimum_required_years(text: str) -> int | None:
    years = [int(match) for match in findall(r"(\d+)\+?\s*years?", text.lower())]
    return min(years) if years else None


def _looks_entry_level(job: JobListing) -> bool:
    text = f"{job.title} {job.description}".lower()
    title = job.title.lower()
    senior_title_markers = [
        "sde-ii",
        "sde ii",
        "sde 2",
        "software development engineer ii",
        "senior",
        "sr.",
        "sr ",
        "principal",
        "lead",
        "manager",
        "level 5",
        "l5",
    ]
    if any(marker in title for marker in senior_title_markers):
        return False

    minimum_years = _minimum_required_years(text)
    if minimum_years is not None:
        return minimum_years <= 2

    entry_markers = ["sde-1", "sde i", "software development engineer i", "junior", "associate"]
    return any(marker in text for marker in entry_markers)


def _salary_matches_goal(job: JobListing) -> bool:
    text = f"{job.title} {job.description} {job.salary_text or ''}".lower()
    has_salary_marker = bool(search(r"(₹|\brs\.?\b|\binr\b|\blpa\b|\blakh\b)", text))
    if not has_salary_marker:
        return job.company.lower() in {"amazon", "amazon jobs"} and "sde" in job.title.lower()

    if search(r"(1[5-9]|[2-9]\d)\s*lpa", text):
        return True

    monthly_amounts = [int(value.replace(",", "")) for value in findall(r"(?:₹|rs\.?|inr)\s*([0-9][0-9,]{4,})", text)]
    return any(amount >= 100000 for amount in monthly_amounts)


def _passes_preferred_filters(job: JobListing, recent_days: int | None) -> bool:
    location_text = f"{job.location or ''} {job.description}".lower()
    if "india" not in location_text and ", ind" not in location_text:
        return False

    title_text = job.title.lower()
    if any(marker in title_text for marker in ["intern", "part time", "part-time"]):
        return False

    if not _looks_entry_level(job):
        return False

    if not _salary_matches_goal(job):
        return False

    if recent_days is not None and job.posted_at is not None:
        age = datetime.now(UTC) - job.posted_at
        return age.days <= recent_days

    return True


async def _fetch_greenhouse_board(
    client: httpx.AsyncClient,
    board_token: str,
) -> list[JobListing]:
    url = f"https://boards-api.greenhouse.io/v1/boards/{quote(board_token)}/jobs"
    response = await client.get(url, params={"content": "true"})
    response.raise_for_status()
    payload = response.json()

    jobs: list[JobListing] = []
    for item in payload.get("jobs", []):
        location = item.get("location") or {}
        jobs.append(
            JobListing(
                job_id=f"greenhouse:{board_token}:{item['id']}",
                title=item.get("title", "Untitled job"),
                company=board_token,
                location=location.get("name"),
                description=_clean_html(item.get("content")),
                url=item.get("absolute_url"),
                source="greenhouse",
                posted_at=None,
            )
        )
    return jobs


async def _fetch_lever_board(
    client: httpx.AsyncClient,
    company_slug: str,
) -> list[JobListing]:
    url = f"https://api.lever.co/v0/postings/{quote(company_slug)}"
    response = await client.get(url, params={"mode": "json"})
    response.raise_for_status()
    payload = response.json()

    jobs: list[JobListing] = []
    for item in payload:
        created_at = item.get("createdAt")
        posted_at = (
            datetime.fromtimestamp(created_at / 1000, tz=UTC)
            if isinstance(created_at, int)
            else None
        )
        jobs.append(
            JobListing(
                job_id=f"lever:{company_slug}:{item['id']}",
                title=item.get("text", "Untitled job"),
                company=company_slug,
                location=(item.get("categories") or {}).get("location"),
                description=_clean_html(item.get("descriptionPlain") or item.get("description")),
                url=item.get("hostedUrl") or item.get("applyUrl"),
                source="lever",
                posted_at=posted_at,
            )
        )
    return jobs


async def _fetch_ashby_board(
    client: httpx.AsyncClient,
    board_name: str,
) -> list[JobListing]:
    url = f"https://api.ashbyhq.com/posting-api/job-board/{quote(board_name)}"
    response = await client.get(url)
    response.raise_for_status()
    payload = response.json()

    jobs: list[JobListing] = []
    for item in payload.get("jobs", []):
        location = item.get("location")
        if isinstance(location, dict):
            location = location.get("location")

        job_id = item.get("id") or item.get("jobPostingId")
        apply_url = item.get("jobUrl") or item.get("applyUrl")
        jobs.append(
            JobListing(
                job_id=f"ashby:{board_name}:{job_id}",
                title=item.get("title", "Untitled job"),
                company=board_name,
                location=location,
                description=_clean_html(
                    item.get("descriptionHtml") or item.get("descriptionPlain")
                ),
                url=apply_url,
                source="ashby",
                posted_at=None,
            )
        )
    return jobs


async def _fetch_amazon_jobs(
    client: httpx.AsyncClient,
    query: str | None,
    limit: int,
) -> list[JobListing]:
    response = await client.get(
        "https://www.amazon.jobs/en/search.json",
        params={
            "base_query": query or "software development engineer",
            "loc_query": "India",
            "country": "IND",
            "sort": "recent",
            "result_limit": max(limit, 10),
        },
        headers={"User-Agent": "Mozilla/5.0", "Accept-Encoding": "identity"},
    )
    response.raise_for_status()
    payload = response.json()

    jobs: list[JobListing] = []
    for item in payload.get("jobs", []):
        description = _clean_html(
            " ".join(
                part
                for part in [
                    item.get("description"),
                    item.get("basic_qualifications"),
                    item.get("preferred_qualifications"),
                ]
                if part
            )
        )
        job_path = item.get("job_path")
        job_url = f"https://www.amazon.jobs{job_path}" if job_path else item.get("url")
        jobs.append(
            JobListing(
                job_id=f"amazon:{item.get('id')}",
                title=item.get("title", "Untitled job"),
                company="Amazon",
                location=item.get("normalized_location") or item.get("city"),
                description=description,
                url=job_url,
                source="amazon",
                posted_at=_parse_amazon_posted_date(item.get("posted_date")),
                employment_type="Full Time",
                salary_text=None,
                salary_confidence="estimated_from_company_and_role",
            )
        )
    return jobs


async def fetch_jobs(
    *,
    query: str | None = None,
    location: str | None = None,
    limit: int = 25,
    preferred_filters: bool = False,
    recent_days: int | None = None,
) -> JobSearchResult:
    greenhouse_boards = _csv_env("GREENHOUSE_BOARD_TOKENS")
    lever_companies = _csv_env("LEVER_COMPANY_SLUGS")
    ashby_boards = _csv_env("ASHBY_BOARD_NAMES")

    include_amazon = os.getenv("ENABLE_AMAZON_JOBS", "true").lower() == "true"
    source_count = len(greenhouse_boards) + len(lever_companies) + len(ashby_boards)
    if include_amazon:
        source_count += 1
    tasks = []
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        if include_amazon:
            tasks.append(_fetch_amazon_jobs(client, query=query, limit=limit))
        tasks.extend(_fetch_greenhouse_board(client, board) for board in greenhouse_boards)
        tasks.extend(_fetch_lever_board(client, slug) for slug in lever_companies)
        tasks.extend(_fetch_ashby_board(client, board) for board in ashby_boards)

        results = await asyncio.gather(*tasks, return_exceptions=True)

    jobs: list[JobListing] = []
    for result in results:
        if isinstance(result, Exception):
            continue
        jobs.extend(result)

    filtered_jobs = [job for job in jobs if _matches_filters(job, query=query, location=location)]
    if preferred_filters:
        filtered_jobs = [
            job for job in filtered_jobs if _passes_preferred_filters(job, recent_days)
        ]
    filtered_jobs = filtered_jobs[:limit]

    return JobSearchResult(
        query=query,
        location=location,
        source_count=source_count,
        job_count=len(filtered_jobs),
        jobs=filtered_jobs,
    )
