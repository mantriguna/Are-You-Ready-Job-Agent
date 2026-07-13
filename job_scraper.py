import asyncio
import hashlib
import json
import logging
import os
from collections.abc import Awaitable
from datetime import UTC, datetime
from html import unescape
from re import findall, search, sub
from urllib.parse import parse_qsl, quote, urlencode, urljoin, urlparse, urlunparse

import httpx
from pydantic import BaseModel, Field, HttpUrl

from company_sources import CompanySource, get_enabled_company_sources


logger = logging.getLogger("ai-job-agent")


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


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _normalize_url(value: str) -> str:
    parsed = urlparse(value)
    keep_params = {
        "jobid",
        "jobId",
        "id",
        "job_id",
        "job",
        "reqid",
        "reqId",
        "source",
        "location",
    }
    query = urlencode(
        [
            (key, val)
            for key, val in parse_qsl(parsed.query, keep_blank_values=True)
            if key in keep_params
        ]
    )
    return urlunparse(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            parsed.path.rstrip("/") or "/",
            "",
            query,
            "",
        )
    )


def _valid_https_url(value: str | None) -> bool:
    if not value:
        return False
    parsed = urlparse(value)
    return parsed.scheme == "https" and bool(parsed.netloc)


def _job_dedupe_key(job: JobListing) -> str:
    if job.url:
        return _normalize_url(str(job.url))
    return "|".join(
        [
            job.company.lower().strip(),
            job.job_id.lower().strip(),
            job.title.lower().strip(),
            (job.location or "").lower().strip(),
        ]
    )


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
        if not _is_india_job(job):
            return False
    elif location and location.lower() not in searchable_text:
        return False

    return True


def _is_india_text(value: str | None) -> bool:
    if not value:
        return False
    text = value.lower()
    india_markers = [
        "india",
        ", ind",
        "bengaluru",
        "bangalore",
        "hyderabad",
        "chennai",
        "pune",
        "gurugram",
        "gurgaon",
        "noida",
        "mumbai",
        "karnataka",
        "telangana",
        "tamil nadu",
        "maharashtra",
        "uttar pradesh",
        "haryana",
        "remote - india",
        "remote india",
    ]
    return any(marker in text for marker in india_markers)


def _is_india_job(job: JobListing) -> bool:
    if job.location:
        return _is_india_text(job.location)
    return _is_india_text(" ".join([job.description, str(job.url)]))


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
        "senior",
        "sr.",
        "sr ",
        "principal",
        "lead",
        "manager",
        "level 5",
        "l5",
        "staff",
        "architect",
        "director",
    ]
    if any(marker in title for marker in senior_title_markers):
        return False

    minimum_years = _minimum_required_years(text)
    if minimum_years is not None:
        return minimum_years <= 4

    entry_markers = ["sde-1", "sde i", "software development engineer i", "junior", "associate"]
    role_markers = [
        "software engineer",
        "software development engineer",
        "developer",
        "backend",
        "python",
        "java",
        "sde",
    ]
    return any(marker in text for marker in entry_markers + role_markers)


def _salary_matches_goal(job: JobListing) -> bool:
    text = f"{job.title} {job.description} {job.salary_text or ''}".lower()
    title = job.title.lower()
    has_salary_marker_clean = bool(
        search(r"(\u20b9|\brs\.?\b|\binr\b|\blpa\b|\blakh\b)", text)
    )
    if not has_salary_marker_clean:
        likely_good_salary_roles = [
            "sde",
            "software engineer",
            "software development engineer",
            "backend",
            "backend engineer",
            "frontend engineer",
            "full stack engineer",
            "data engineer",
            "devops engineer",
            "platform engineer",
            "site reliability",
            "sre",
            "cloud engineer",
            "machine learning",
            "ml engineer",
            "python developer",
            "java developer",
            "ai developer",
        ]
        return any(marker in title for marker in likely_good_salary_roles)

    if search(r"(1[5-9]|[2-9]\d)\s*lpa", text):
        return True

    monthly_amounts_clean = [
        int(value.replace(",", ""))
        for value in findall(r"(?:\u20b9|rs\.?|inr)\s*([0-9][0-9,]{4,})", text)
    ]
    return any(amount >= 100000 for amount in monthly_amounts_clean)
    has_salary_marker = bool(search(r"(₹|\brs\.?\b|\binr\b|\blpa\b|\blakh\b)", text))
    if not has_salary_marker:
        return job.company.lower() in {"amazon", "amazon jobs"} and "sde" in job.title.lower()

    if search(r"(1[5-9]|[2-9]\d)\s*lpa", text):
        return True

    monthly_amounts = [int(value.replace(",", "")) for value in findall(r"(?:₹|rs\.?|inr)\s*([0-9][0-9,]{4,})", text)]
    return any(amount >= 100000 for amount in monthly_amounts)


def _passes_preferred_filters(job: JobListing, recent_days: int | None) -> bool:
    if not _is_india_job(job):
        return False

    title_text = job.title.lower()
    if any(marker in title_text for marker in ["intern", "part time", "part-time"]):
        return False

    if not _salary_matches_goal(job):
        return False

    if not _looks_entry_level(job):
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


async def _fetch_greenhouse_source(
    client: httpx.AsyncClient,
    source: CompanySource,
) -> list[JobListing]:
    board_token = source.source_key or source.company_name.lower().replace(" ", "")
    jobs = await _fetch_greenhouse_board(client, board_token)
    normalized_jobs: list[JobListing] = []
    for job in jobs:
        updated = job.model_copy(
            update={
                "job_id": f"greenhouse:{source.company_name.lower()}:{job.job_id.split(':')[-1]}",
                "company": source.company_name,
            }
        )
        if _is_india_job(updated):
            normalized_jobs.append(updated)
    return normalized_jobs


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


async def _fetch_lever_source(
    client: httpx.AsyncClient,
    source: CompanySource,
) -> list[JobListing]:
    company_slug = source.source_key or source.company_name.lower().replace(" ", "")
    jobs = await _fetch_lever_board(client, company_slug)
    normalized_jobs: list[JobListing] = []
    for job in jobs:
        updated = job.model_copy(
            update={
                "job_id": f"lever:{source.company_name.lower()}:{job.job_id.split(':')[-1]}",
                "company": source.company_name,
            }
        )
        if _is_india_job(updated):
            normalized_jobs.append(updated)
    return normalized_jobs


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


async def _fetch_ashby_source(
    client: httpx.AsyncClient,
    source: CompanySource,
) -> list[JobListing]:
    board_name = source.source_key or source.domain.split(".")[0]
    jobs = await _fetch_ashby_board(client, board_name)
    normalized_jobs: list[JobListing] = []
    for job in jobs:
        updated = job.model_copy(
            update={
                "job_id": f"ashby:{source.company_name.lower()}:{job.job_id.split(':')[-1]}",
                "company": source.company_name,
            }
        )
        if _is_india_job(updated):
            normalized_jobs.append(updated)
    return normalized_jobs


async def _fetch_amazon_jobs(
    client: httpx.AsyncClient,
    query: str | None,
    limit: int,
) -> list[JobListing]:
    jobs: list[JobListing] = []
    max_pages = _int_env("MAX_PAGES_PER_SOURCE", 0)
    page_size = min(max(limit, 50), 100)
    offset = 0
    seen_ids: set[str] = set()

    while True:
        if max_pages and (offset // page_size) >= max_pages:
            logger.warning("Amazon pagination stopped by MAX_PAGES_PER_SOURCE=%s", max_pages)
            break

        response = await client.get(
            "https://www.amazon.jobs/en/search.json",
            params={
                "base_query": query or "software development engineer",
                "loc_query": "India",
                "country": "IND",
                "sort": "recent",
                "result_limit": page_size,
                "offset": offset,
            },
            headers={"User-Agent": "AreYouReadyJobAgent/1.0", "Accept-Encoding": "identity"},
        )
        response.raise_for_status()
        payload = response.json()
        page_jobs = payload.get("jobs", [])
        if not page_jobs:
            break

        new_on_page = 0
        for item in page_jobs:
            item_id = str(item.get("id") or "")
            if not item_id or item_id in seen_ids:
                continue
            seen_ids.add(item_id)
            new_on_page += 1
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
            if not _valid_https_url(job_url):
                continue
            jobs.append(
                JobListing(
                    job_id=f"amazon:{item_id}",
                    title=item.get("title", "Untitled job"),
                    company="Amazon",
                    location=item.get("normalized_location") or item.get("city"),
                    description=description,
                    url=_normalize_url(job_url),
                    source="amazon",
                    posted_at=_parse_amazon_posted_date(item.get("posted_date")),
                    employment_type="Full Time",
                    salary_text=None,
                    salary_confidence="unknown",
                )
            )
        if new_on_page == 0:
            break
        offset += page_size
    return jobs


def _workday_endpoint(source: CompanySource) -> tuple[str, str] | None:
    workday_url = source.source_key or source.careers_url
    parsed = urlparse(workday_url)
    site = parsed.path.strip("/").split("/")[0]
    if not parsed.netloc or not site:
        return None
    tenant = parsed.netloc.split(".")[0]
    return f"https://{parsed.netloc}/wday/cxs/{tenant}/{site}/jobs", site


async def _fetch_workday_jobs(
    client: httpx.AsyncClient,
    source: CompanySource,
    query: str | None,
) -> list[JobListing]:
    endpoint = _workday_endpoint(source)
    if not endpoint:
        return []
    url, site = endpoint
    workday_base_url = source.source_key or source.careers_url
    jobs: list[JobListing] = []
    max_pages = _int_env("MAX_PAGES_PER_SOURCE", 0)
    page_size = 20
    offset = 0
    seen_ids: set[str] = set()

    while True:
        if max_pages and (offset // page_size) >= max_pages:
            logger.warning("%s pagination stopped by MAX_PAGES_PER_SOURCE=%s", source.company_name, max_pages)
            break
        payload = {
            "appliedFacets": {},
            "limit": page_size,
            "offset": offset,
            "searchText": query or "software",
        }
        response = await client.post(
            url,
            json=payload,
            headers={"User-Agent": "AreYouReadyJobAgent/1.0", "Accept": "application/json"},
        )
        response.raise_for_status()
        data = response.json()
        page_jobs = data.get("jobPostings") or data.get("jobs") or []
        if not page_jobs:
            break
        new_on_page = 0
        for item in page_jobs:
            bullet_fields = item.get("bulletFields") or []
            external_id = str(
                (bullet_fields[0] if bullet_fields else None)
                or item.get("externalPath")
                or item.get("id")
                or item.get("title")
            )
            if not external_id or external_id in seen_ids:
                continue
            seen_ids.add(external_id)
            new_on_page += 1
            external_path = item.get("externalPath")
            if not external_path:
                continue
            job_url = urljoin(workday_base_url.rstrip("/") + "/", str(external_path))
            if not _valid_https_url(job_url):
                continue
            title = item.get("title") or item.get("jobTitle") or "Untitled job"
            location = item.get("locationsText") or item.get("location")
            posted_at = None
            posted = item.get("postedOn") or item.get("startDate")
            if isinstance(posted, str):
                try:
                    posted_at = datetime.fromisoformat(posted.replace("Z", "+00:00"))
                except ValueError:
                    posted_at = None
            job = JobListing(
                job_id=f"workday:{source.company_name.lower()}:{external_id}",
                title=title,
                company=source.company_name,
                location=location,
                description=_clean_html(item.get("description") or item.get("jobDescription") or title),
                url=_normalize_url(job_url),
                source=f"workday:{site}",
                posted_at=posted_at,
                employment_type=item.get("timeType"),
                salary_confidence="unknown",
            )
            if not _is_india_job(job):
                continue
            jobs.append(job)
        if new_on_page == 0:
            break
        offset += page_size
    return jobs


def _is_direct_job_detail_url(job_url: str) -> bool:
    parsed = urlparse(job_url)
    path = parsed.path.lower()
    query = parsed.query.lower()
    direct_markers = [
        "/jobs/results/",
        "/details/",
        "/job/",
        "/jobs/",
        "/careers/jobs/",
        "/open-positions/",
    ]
    category_markers = [
        "/careers/all-jobs",
        "/search-jobs/",
        "/category/",
        "/engineering-jobs",
        "/search-results",
        "/career-page",
    ]
    if any(marker in path for marker in category_markers):
        return False
    return any(marker in path for marker in direct_markers) or "jobid=" in query or "job_id=" in query


def _title_from_job_url(job_url: str, fallback: str) -> str:
    parsed = urlparse(job_url)
    pieces = [part for part in parsed.path.split("/") if part]
    if pieces:
        slug = pieces[-1]
        slug = sub(r"^\d+[-_]*", "", slug)
        slug = sub(r"^[a-f0-9-]{20,}[-_]*", "", slug)
        title = sub(r"[-_]+", " ", slug).strip()
        if title and not title.isdigit() and len(title) > 3:
            return title.title()
    return fallback


def _parse_flexible_date(value: str | None) -> datetime | None:
    if not value:
        return None
    for candidate in [value, value.replace("Z", "+00:00")]:
        try:
            parsed = datetime.fromisoformat(candidate)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def _extract_embedded_search_jobs(source: CompanySource, html: str) -> list[JobListing]:
    jobs: list[JobListing] = []
    decoder = json.JSONDecoder()
    cursor = 0
    while True:
        key_index = html.find('"eagerLoadRefineSearch"', cursor)
        if key_index == -1:
            break
        cursor = key_index + 1
        colon_index = html.find(":", key_index)
        if colon_index == -1:
            continue
        try:
            payload, parsed_length = decoder.raw_decode(html[colon_index + 1 :])
        except json.JSONDecodeError:
            continue
        cursor = colon_index + 1 + parsed_length
        if not isinstance(payload, dict):
            continue
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        page_jobs = data.get("jobs") if isinstance(data.get("jobs"), list) else []
        for item in page_jobs:
            if not isinstance(item, dict):
                continue
            apply_url = item.get("applyUrl") or item.get("url")
            if not _valid_https_url(apply_url):
                continue
            title = item.get("title") or item.get("jobTitle") or item.get("displayName")
            if not title:
                title = _title_from_job_url(str(apply_url), source.company_name)
            location = (
                item.get("cityStateCountry")
                or item.get("location")
                or ", ".join(item.get("multi_location") or [])
                or item.get("address")
                or item.get("country")
            )
            description = _clean_html(
                item.get("descriptionTeaser")
                or (item.get("ml_job_parser") or {}).get("descriptionTeaser")
                or title
            )
            job_id = item.get("reqId") or item.get("jobId") or item.get("jobSeqNo") or apply_url
            job = JobListing(
                job_id=f"embedded:{source.company_name.lower()}:{job_id}",
                title=title,
                company=source.company_name,
                location=location,
                description=f"{description} {location or ''}",
                url=_normalize_url(str(apply_url)),
                source="embedded_search",
                posted_at=_parse_flexible_date(item.get("postedDate") or item.get("dateCreated")),
                employment_type=item.get("type"),
                salary_confidence="unknown",
            )
            if not _is_india_job(job):
                continue
            jobs.append(job)
    return jobs


async def _fetch_generic_official_jobs(
    client: httpx.AsyncClient,
    source: CompanySource,
    query: str | None,
) -> list[JobListing]:
    response = await client.get(
        source.careers_url,
        headers={"User-Agent": "AreYouReadyJobAgent/1.0", "Accept": "text/html,application/xhtml+xml"},
    )
    response.raise_for_status()
    content_type = response.headers.get("content-type", "")
    if "text/html" not in content_type and "application/xhtml" not in content_type:
        return []
    html = response.text[: int(os.getenv("HTTP_MAX_RESPONSE_CHARS", "2000000"))]
    embedded_jobs = _extract_embedded_search_jobs(source, html)
    if embedded_jobs:
        return embedded_jobs
    link_matches = findall(r"<a\b[^>]*href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", html, flags=2)
    jobs: list[JobListing] = []
    seen_urls: set[str] = set()
    query_terms = [term for term in (query or "software engineer").lower().split() if len(term) > 2]
    for href, label_html in link_matches:
        label = _clean_html(label_html)
        combined = f"{label} {href}".lower()
        if not any(term in combined for term in query_terms):
            continue
        if not any(marker in combined for marker in ["job", "career", "position", "software", "engineer", "developer", "sde"]):
            continue
        job_url = urljoin(source.careers_url, href)
        parsed_job = urlparse(job_url)
        if parsed_job.scheme != "https":
            continue
        if not _is_direct_job_detail_url(job_url):
            continue
        if parsed_job.netloc.lower().removeprefix("www.") != source.domain.removeprefix("www."):
            allowed = [domain.lower().removeprefix("www.") for domain in source.official_domains]
            if parsed_job.netloc.lower().removeprefix("www.") not in allowed:
                continue
        normalized_url = _normalize_url(job_url)
        if normalized_url in seen_urls:
            continue
        seen_urls.add(normalized_url)
        stable_id = hashlib.sha256(normalized_url.encode("utf-8")).hexdigest()[:16]
        title = _title_from_job_url(job_url, label or source.company_name)
        job = JobListing(
            job_id=f"official:{source.company_name.lower()}:{stable_id}",
            title=title,
            company=source.company_name,
            location="India" if _is_india_text(combined) else None,
            description=f"{label} {job_url}",
            url=normalized_url,
            source="official_html",
            salary_confidence="unknown",
        )
        if not _is_india_job(job):
            continue
        jobs.append(job)
    return jobs


async def _fetch_company_source_jobs(
    client: httpx.AsyncClient,
    source: CompanySource,
    query: str | None,
    limit: int,
) -> list[JobListing]:
    if source.source_type == "amazon_json":
        return await _fetch_amazon_jobs(client, query=query, limit=limit)
    if source.source_type == "workday":
        return await _fetch_workday_jobs(client, source, query=query)
    if source.source_type == "greenhouse":
        return await _fetch_greenhouse_source(client, source)
    if source.source_type == "lever":
        return await _fetch_lever_source(client, source)
    if source.source_type == "ashby":
        return await _fetch_ashby_source(client, source)
    return await _fetch_generic_official_jobs(client, source, query=query)


async def _fetch_rapidapi_jobs(
    client: httpx.AsyncClient,
    query: str | None,
    limit: int,
) -> list[JobListing]:
    rapidapi_key = os.getenv("RAPIDAPI_KEY")
    if not rapidapi_key:
        return []

    host = os.getenv("RAPIDAPI_JOBS_HOST", "jsearch.p.rapidapi.com")
    response = await client.get(
        f"https://{host}/search",
        params={
            "query": f"{query or 'software development engineer'} in India",
            "page": "1",
            "num_pages": "1",
            "date_posted": "today",
            "employment_types": "FULLTIME,CONTRACTOR",
        },
        headers={
            "X-RapidAPI-Key": rapidapi_key,
            "X-RapidAPI-Host": host,
        },
    )
    response.raise_for_status()
    payload = response.json()

    jobs: list[JobListing] = []
    for item in payload.get("data", [])[:limit]:
        job_id = item.get("job_id") or item.get("job_apply_link") or item.get("job_title")
        apply_url = item.get("job_apply_link") or item.get("job_google_link")
        if not job_id or not apply_url:
            continue

        posted_at = None
        posted_timestamp = item.get("job_posted_at_timestamp")
        if isinstance(posted_timestamp, int):
            posted_at = datetime.fromtimestamp(posted_timestamp, tz=UTC)

        jobs.append(
            JobListing(
                job_id=f"rapidapi:{job_id}",
                title=item.get("job_title", "Untitled job"),
                company=item.get("employer_name", "Unknown company"),
                location=item.get("job_location"),
                description=_clean_html(item.get("job_description")),
                url=apply_url,
                source=item.get("job_publisher") or "rapidapi",
                posted_at=posted_at,
                employment_type=item.get("job_employment_type"),
                salary_text=item.get("job_salary"),
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
    include_amazon: bool | None = None,
    include_rapidapi: bool | None = None,
    include_boards: bool = True,
    include_official_sources: bool | None = None,
    apply_query_filter: bool = True,
) -> JobSearchResult:
    greenhouse_boards = _csv_env("GREENHOUSE_BOARD_TOKENS") if include_boards else []
    lever_companies = _csv_env("LEVER_COMPANY_SLUGS") if include_boards else []
    ashby_boards = _csv_env("ASHBY_BOARD_NAMES") if include_boards else []

    if include_amazon is None:
        include_amazon = os.getenv("ENABLE_AMAZON_JOBS", "true").lower() == "true"
    if include_rapidapi is None:
        include_rapidapi = bool(os.getenv("RAPIDAPI_KEY"))
    if include_official_sources is None:
        include_official_sources = os.getenv("ENABLE_OFFICIAL_COMPANY_SOURCES", "true").lower() == "true"
    source_count = len(greenhouse_boards) + len(lever_companies) + len(ashby_boards)
    official_sources = get_enabled_company_sources() if include_official_sources else []
    if include_amazon and not include_official_sources:
        source_count += 1
    source_count += len(official_sources)
    if include_rapidapi:
        source_count += 1
    tasks: list[tuple[str, Awaitable[list[JobListing]]]] = []
    timeout = _int_env("HTTP_TIMEOUT_SECONDS", 30)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        if include_amazon and not include_official_sources:
            tasks.append(("amazon", _fetch_amazon_jobs(client, query=query, limit=limit)))
        if official_sources:
            official_limit = max(limit, _int_env("JOB_SOURCE_BATCH_SIZE", 100), 50)
            tasks.extend(
                (
                    f"official:{source.company_name}",
                    _fetch_company_source_jobs(client, source, query=query, limit=official_limit),
                )
                for source in official_sources
            )
        if include_rapidapi:
            tasks.append(("rapidapi", _fetch_rapidapi_jobs(client, query=query, limit=limit)))
        tasks.extend(
            (f"greenhouse:{board}", _fetch_greenhouse_board(client, board))
            for board in greenhouse_boards
        )
        tasks.extend(
            (f"lever:{slug}", _fetch_lever_board(client, slug))
            for slug in lever_companies
        )
        tasks.extend(
            (f"ashby:{board}", _fetch_ashby_board(client, board))
            for board in ashby_boards
        )

        concurrency = max(1, _int_env("JOB_SOURCE_CONCURRENCY", 5))
        semaphore = asyncio.Semaphore(concurrency)

        async def run_source(task: Awaitable[list[JobListing]]) -> list[JobListing]:
            async with semaphore:
                return await task

        results = await asyncio.gather(
            *(run_source(task) for _, task in tasks),
            return_exceptions=True,
        )

    jobs: list[JobListing] = []
    for (source_name, _), result in zip(tasks, results):
        if isinstance(result, Exception):
            logger.warning("Job source %s failed: %s", source_name, result)
            continue
        jobs.extend(result)

    deduped_jobs: list[JobListing] = []
    seen_keys: set[str] = set()
    for job in jobs:
        key = _job_dedupe_key(job)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        deduped_jobs.append(job)

    filter_query = query if apply_query_filter else None
    filtered_jobs = [
        job for job in deduped_jobs if _matches_filters(job, query=filter_query, location=location)
    ]
    if preferred_filters:
        filtered_jobs = [
            job for job in filtered_jobs if _passes_preferred_filters(job, recent_days)
        ]
    return JobSearchResult(
        query=query,
        location=location,
        source_count=source_count,
        job_count=len(filtered_jobs),
        jobs=filtered_jobs,
    )
