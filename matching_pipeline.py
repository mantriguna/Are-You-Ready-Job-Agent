import asyncio
import logging
import os
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, HttpUrl

from ai_engine import JobMatchEvaluation, evaluate_job_match
from database import (
    get_sent_job_ids,
    get_user_profile,
    replace_latest_job_alerts,
    save_sent_job,
)
from job_scraper import JobListing, JobSearchResult, fetch_jobs
from resume_tailor import generate_tailored_resume_txt
from whatsapp import send_document_message, send_template_message, send_text_message


logger = logging.getLogger("ai-job-agent")


class EvaluatedJob(BaseModel):
    job_id: str
    title: str
    company: str
    location: str | None
    url: HttpUrl
    evaluation: JobMatchEvaluation
    action: Literal[
        "would_send",
        "sent",
        "sent_template",
        "skipped_low_match",
        "send_failed",
        "evaluation_failed",
    ]
    error: str | None = None
    tailored_resume_file: str | None = None
    job_number: int | None = None


class UserJobRunResult(BaseModel):
    whatsapp_number: str
    query: str
    search_queries: list[str]
    recent_days: int | None
    ignore_duplicates: bool
    scraped_count: int
    duplicate_count: int
    evaluated_count: int
    alert_count: int
    dry_run: bool
    results: list[EvaluatedJob]


def _format_job_alert(
    job: JobListing, evaluation: JobMatchEvaluation, job_number: int | None = None
) -> str:
    location = f"\nLocation: {job.location}" if job.location else ""
    skills = ", ".join(evaluation.matched_skills[:6]) or "Relevant profile match"
    prefix = f"Job {job_number}: " if job_number else "Job match: "
    return (
        f"{prefix}{job.title}\n"
        f"Company: {job.company}{location}\n"
        f"Match: {evaluation.match_percentage}%\n"
        f"Why: {evaluation.short_reason}\n"
        f"Matched: {skills}\n"
        f"Apply: {job.url}"
    )


def _public_resume_url(resume_file: str) -> str | None:
    base_url = os.getenv("PUBLIC_BASE_URL")
    if not base_url:
        return None
    return f"{base_url.rstrip('/')}/generated-resumes/{resume_file}"


def _build_search_queries(target_title: str) -> list[str]:
    configured_queries = os.getenv(
        "PREFERRED_JOB_QUERIES",
        "Software Development Engineer,SDE-1,SDE I,Backend Engineer,Python Developer,Java Developer",
    )
    candidates = [
        query.strip()
        for value in [target_title, configured_queries]
        for query in value.split(",")
        if query.strip()
    ]

    search_queries: list[str] = []
    seen: set[str] = set()
    for query in candidates:
        normalized = query.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        search_queries.append(query)
    return search_queries


def _compact_text(value: str, max_length: int) -> str:
    clean = " ".join(value.split())
    if len(clean) <= max_length:
        return clean
    return f"{clean[: max_length - 3].rstrip()}..."


def _format_daily_summary(alerts: list[dict]) -> str:
    chunks = _format_daily_summary_chunks(alerts)
    return chunks[0] if chunks else ""


def _format_daily_summary_chunks(alerts: list[dict]) -> list[str]:
    lines = []
    chunks: list[str] = []
    max_summary_chars = 760
    for alert in alerts:
        location = (alert.get("location") or "").split(",")[0].strip()
        location_text = f" | {location}" if location else ""
        title = _compact_text(str(alert["title"]), 65)
        line = (
            f"{alert['job_number']}. {alert['company']} | {title} "
            f"| {alert['match_percentage']}%{location_text} | Link: {alert['job_url']}"
        )
        next_summary = " || ".join([*lines, line])
        if len(next_summary) > max_summary_chars and lines:
            chunks.append(" || ".join(lines))
            lines = [line]
            continue
        lines.append(line)
    if lines:
        chunks.append(" || ".join(lines))
    return chunks


def _priority_score(job: JobListing, evaluation: JobMatchEvaluation) -> int:
    text = f"{job.title} {job.description} {job.salary_text or ''}".lower()
    score = evaluation.match_percentage
    if job.company.lower() == "amazon":
        score += 25
    if job.posted_at:
        age_days = (datetime.now(UTC) - job.posted_at).days
        if age_days <= 1:
            score += 15
        elif age_days <= 7:
            score += 8
    if any(marker in text for marker in ["sde-1", "sde i", "associate", "junior", "0-2"]):
        score += 10
    if any(marker in text for marker in ["full time", "full-time", "contract", "contractual"]):
        score += 5
    if any(marker in text for marker in ["lpa", "lakh", "inr", "rs."]):
        score += 5
    return score


async def run_user_job_search(
    *,
    whatsapp_number: str,
    limit: int = 10,
    threshold: int = 40,
    dry_run: bool = True,
    preferred_filters: bool = True,
    recent_days: int | None = 1,
    ignore_duplicates: bool = False,
    use_template_alert: bool = False,
    max_evaluations: int | None = None,
) -> UserJobRunResult:
    profile = get_user_profile(whatsapp_number)
    if not profile:
        raise ValueError("WhatsApp profile not found.")

    target_title = profile.get("target_title")
    experience_summary = profile.get("experience_summary")
    if not target_title or not experience_summary:
        raise ValueError("WhatsApp profile is incomplete.")

    search_queries = _build_search_queries(target_title)
    evaluation_pool_limit = int(os.getenv("JOB_EVALUATION_POOL_LIMIT", str(max(limit, 15))))
    target_pool_size = max_evaluations or evaluation_pool_limit
    fetch_limit = max(limit, target_pool_size, 1)
    scraped_jobs: list[JobListing] = []
    seen_job_ids: set[str] = set()
    source_count = 0
    for search_query in search_queries:
        query_result = await fetch_jobs(
            query=search_query,
            location="India",
            limit=fetch_limit,
            preferred_filters=preferred_filters,
            recent_days=recent_days,
        )
        source_count = max(source_count, query_result.source_count)
        for job in query_result.jobs:
            if job.job_id in seen_job_ids:
                continue
            seen_job_ids.add(job.job_id)
            scraped_jobs.append(job)
        if len(scraped_jobs) >= target_pool_size:
            break

    if not scraped_jobs:
        query_result = await fetch_jobs(
            query=target_title,
            location="India",
            limit=fetch_limit,
            preferred_filters=preferred_filters,
            recent_days=recent_days,
        )
        source_count = max(source_count, query_result.source_count)
        scraped_jobs = query_result.jobs

    scraped = JobSearchResult(
        query=target_title,
        location="India",
        source_count=source_count,
        job_count=len(scraped_jobs),
        jobs=scraped_jobs[:target_pool_size],
    )

    job_ids = [job.job_id for job in scraped.jobs]
    duplicate_ids = get_sent_job_ids(whatsapp_number, job_ids)
    fresh_jobs = (
        scraped.jobs
        if ignore_duplicates
        else [job for job in scraped.jobs if job.job_id not in duplicate_ids]
    )

    results: list[EvaluatedJob] = []
    alert_candidates: list[tuple[JobListing, JobMatchEvaluation]] = []
    lower_match_candidates: list[tuple[JobListing, JobMatchEvaluation]] = []
    jobs_to_evaluate = fresh_jobs[:max_evaluations] if max_evaluations else fresh_jobs
    fill_limit_with_lower_matches = (
        os.getenv("FILL_DAILY_LIMIT_WITH_LOWER_MATCHES", "true").lower() == "true"
    )
    send_all_above_threshold = (
        os.getenv("SEND_ALL_ABOVE_THRESHOLD_MATCHES", "true").lower() == "true"
    )

    for job in jobs_to_evaluate:
        try:
            evaluation = await asyncio.to_thread(
                evaluate_job_match,
                target_title=target_title,
                experience_summary=experience_summary,
                resume_text=profile.get("resume_text"),
                job_title=job.title,
                job_description=job.description,
            )
        except Exception as exc:
            logger.exception("Failed to evaluate job match for %s", job.job_id)
            results.append(
                EvaluatedJob(
                    job_id=job.job_id,
                    title=job.title,
                    company=job.company,
                    location=job.location,
                    url=job.url,
                    evaluation=JobMatchEvaluation(
                        match_percentage=0,
                        matched_skills=[],
                        missing_skills=[],
                        short_reason="Evaluation failed before a match score was produced.",
                        should_alert=False,
                    ),
                    action="evaluation_failed",
                    error=str(exc),
                )
            )
            continue

        should_alert = evaluation.should_alert and evaluation.match_percentage >= threshold
        if not should_alert:
            if fill_limit_with_lower_matches and evaluation.match_percentage > 0:
                lower_match_candidates.append((job, evaluation))
            else:
                results.append(
                    EvaluatedJob(
                        job_id=job.job_id,
                        title=job.title,
                        company=job.company,
                        location=job.location,
                        url=job.url,
                        evaluation=evaluation,
                        action="skipped_low_match",
                    )
                )
            continue

        alert_candidates.append((job, evaluation))

    def sort_key(item: tuple[JobListing, JobMatchEvaluation]) -> tuple[bool, int, str]:
        return (
            item[0].company.lower() != "amazon",
            -_priority_score(item[0], item[1]),
            item[0].title.lower(),
        )

    alert_candidates.sort(key=sort_key)
    lower_match_candidates.sort(key=sort_key)
    selected_alerts = (
        alert_candidates if send_all_above_threshold else alert_candidates[:limit]
    )
    if fill_limit_with_lower_matches and len(selected_alerts) < limit:
        selected_job_ids = {job.job_id for job, _ in selected_alerts}
        for job, evaluation in lower_match_candidates:
            if job.job_id in selected_job_ids:
                continue
            selected_alerts.append((job, evaluation))
            selected_job_ids.add(job.job_id)
            if len(selected_alerts) >= limit:
                break

    selected_job_ids = {job.job_id for job, _ in selected_alerts}
    for job, evaluation in lower_match_candidates:
        if job.job_id in selected_job_ids:
            continue
        results.append(
            EvaluatedJob(
                job_id=job.job_id,
                title=job.title,
                company=job.company,
                location=job.location,
                url=job.url,
                evaluation=evaluation,
                action="skipped_low_match",
            )
        )

    latest_alerts: list[dict] = []
    pending_sent_jobs: list[dict[str, str | int]] = []
    summary_template_name = os.getenv("WHATSAPP_DAILY_SUMMARY_TEMPLATE_NAME")

    for job_number, (job, evaluation) in enumerate(selected_alerts, start=1):
        action: Literal["would_send", "sent", "sent_template", "send_failed"]
        action = "would_send" if dry_run else ("sent_template" if summary_template_name else "sent")
        error = None
        tailored_resume_path = None

        if not use_template_alert and not summary_template_name:
            try:
                tailored_resume_path = generate_tailored_resume_txt(
                    profile=profile,
                    job=job,
                    evaluation=evaluation,
                )
            except Exception as exc:
                logger.exception("Failed to generate tailored resume for %s", job.job_id)
                error = f"resume_generation_failed: {exc}"

        if not dry_run and not summary_template_name:
            try:
                alert_text = _format_job_alert(job, evaluation, job_number)
                if use_template_alert:
                    await send_template_message(
                        whatsapp_number=whatsapp_number,
                        template_name=os.getenv(
                            "WHATSAPP_JOB_TEMPLATE_NAME", "job_match_alert"
                        ),
                        language_code=os.getenv(
                            "WHATSAPP_TEMPLATE_LANGUAGE", "en_US"
                        ),
                        body_parameters=[
                            f"Job {job_number}: {job.title}",
                            job.company,
                            f"{evaluation.match_percentage}%",
                            str(job.url),
                        ],
                    )
                    action = "sent_template"
                elif tailored_resume_path:
                    document_url = _public_resume_url(tailored_resume_path.name)
                    if document_url:
                        await send_document_message(
                            whatsapp_number=whatsapp_number,
                            document_url=document_url,
                            filename=tailored_resume_path.name,
                            caption=alert_text,
                        )
                    else:
                        await send_text_message(
                            whatsapp_number,
                            f"{alert_text}\n\nTailored resume file: {tailored_resume_path}",
                        )
                else:
                    await send_text_message(whatsapp_number, alert_text)
                save_sent_job(
                    whatsapp_number=whatsapp_number,
                    job_id=job.job_id,
                    job_title=job.title,
                    company_name=job.company,
                    job_url=str(job.url),
                    match_percentage=evaluation.match_percentage,
                )
            except Exception as exc:
                logger.exception("Failed to send job alert for %s", job.job_id)
                action = "send_failed"
                error = str(exc)
        elif not dry_run and summary_template_name:
            pending_sent_jobs.append(
                {
                    "whatsapp_number": whatsapp_number,
                    "job_id": job.job_id,
                    "job_title": job.title,
                    "company_name": job.company,
                    "job_url": str(job.url),
                    "match_percentage": evaluation.match_percentage,
                }
            )

        latest_alerts.append(
            {
                "job_number": job_number,
                "job_id": job.job_id,
                "title": job.title,
                "company": job.company,
                "location": job.location,
                "job_url": str(job.url),
                "description": job.description,
                "match_percentage": evaluation.match_percentage,
                "evaluation": evaluation.model_dump(),
                "resume_file": str(tailored_resume_path) if tailored_resume_path else None,
            }
        )
        results.append(
            EvaluatedJob(
                job_id=job.job_id,
                title=job.title,
                company=job.company,
                location=job.location,
                url=job.url,
                evaluation=evaluation,
                action=action,
                error=error,
                tailored_resume_file=str(tailored_resume_path) if tailored_resume_path else None,
                job_number=job_number,
            )
        )

    if not dry_run and summary_template_name and latest_alerts:
        try:
            summary_chunks = _format_daily_summary_chunks(latest_alerts)
            for chunk_index, summary_chunk in enumerate(summary_chunks, start=1):
                period = (
                    f"today, part {chunk_index}/{len(summary_chunks)}"
                    if len(summary_chunks) > 1
                    else "today"
                )
                await send_template_message(
                    whatsapp_number=whatsapp_number,
                    template_name=summary_template_name,
                    language_code=os.getenv("WHATSAPP_TEMPLATE_LANGUAGE", "en_US"),
                    body_parameters=[
                        str(len(latest_alerts)),
                        period,
                        summary_chunk,
                    ],
                )
            for sent_job in pending_sent_jobs:
                save_sent_job(**sent_job)
        except Exception as exc:
            logger.exception("Failed to send daily summary template.")
            for result in results:
                if result.action == "sent_template":
                    result.action = "send_failed"
                    result.error = str(exc)

    if not dry_run:
        try:
            replace_latest_job_alerts(whatsapp_number, latest_alerts)
        except Exception:
            logger.exception("Failed to save latest numbered job alerts.")

    return UserJobRunResult(
        whatsapp_number=whatsapp_number,
        query=target_title,
        search_queries=search_queries,
        recent_days=recent_days,
        ignore_duplicates=ignore_duplicates,
        scraped_count=scraped.job_count,
        duplicate_count=len(duplicate_ids),
        evaluated_count=len(jobs_to_evaluate),
        alert_count=len(selected_alerts),
        dry_run=dry_run,
        results=results,
    )
