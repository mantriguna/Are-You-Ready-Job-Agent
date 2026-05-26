import logging
import os
from typing import Literal

from pydantic import BaseModel, HttpUrl

from ai_engine import JobMatchEvaluation, evaluate_job_match
from database import get_sent_job_ids, get_user_profile, save_sent_job
from job_scraper import JobListing, fetch_jobs
from resume_tailor import generate_tailored_resume_txt
from whatsapp import send_document_message, send_text_message


logger = logging.getLogger("ai-job-agent")


class EvaluatedJob(BaseModel):
    job_id: str
    title: str
    company: str
    location: str | None
    url: HttpUrl
    evaluation: JobMatchEvaluation
    action: Literal["would_send", "sent", "skipped_low_match", "send_failed"]
    error: str | None = None
    tailored_resume_file: str | None = None


class UserJobRunResult(BaseModel):
    whatsapp_number: str
    query: str
    scraped_count: int
    duplicate_count: int
    evaluated_count: int
    alert_count: int
    dry_run: bool
    results: list[EvaluatedJob]


def _format_job_alert(job: JobListing, evaluation: JobMatchEvaluation) -> str:
    location = f"\nLocation: {job.location}" if job.location else ""
    skills = ", ".join(evaluation.matched_skills[:6]) or "Relevant profile match"
    return (
        f"Job match: {job.title}\n"
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


async def run_user_job_search(
    *,
    whatsapp_number: str,
    limit: int = 10,
    threshold: int = 75,
    dry_run: bool = True,
    preferred_filters: bool = True,
    recent_days: int | None = 1,
) -> UserJobRunResult:
    profile = get_user_profile(whatsapp_number)
    if not profile:
        raise ValueError("WhatsApp profile not found.")

    target_title = profile.get("target_title")
    experience_summary = profile.get("experience_summary")
    if not target_title or not experience_summary:
        raise ValueError("WhatsApp profile is incomplete.")

    scraped = await fetch_jobs(
        query=target_title,
        location="India",
        limit=limit,
        preferred_filters=preferred_filters,
        recent_days=recent_days,
    )
    if scraped.job_count == 0 and " " in target_title:
        fallback_query = target_title.split()[0]
        scraped = await fetch_jobs(
            query=fallback_query,
            location="India",
            limit=limit,
            preferred_filters=preferred_filters,
            recent_days=recent_days,
        )
    if scraped.job_count == 0 and preferred_filters:
        preferred_queries = [
            query.strip()
            for query in os.getenv(
                "PREFERRED_JOB_QUERIES",
                "SDE-1,Software Development Engineer,Backend Engineer",
            ).split(",")
            if query.strip()
        ]
        for preferred_query in preferred_queries:
            scraped = await fetch_jobs(
                query=preferred_query,
                location="India",
                limit=limit,
                preferred_filters=preferred_filters,
                recent_days=recent_days,
            )
            if scraped.job_count:
                break
    job_ids = [job.job_id for job in scraped.jobs]
    duplicate_ids = get_sent_job_ids(whatsapp_number, job_ids)
    fresh_jobs = [job for job in scraped.jobs if job.job_id not in duplicate_ids]

    results: list[EvaluatedJob] = []
    alert_count = 0

    for job in fresh_jobs:
        evaluation = evaluate_job_match(
            target_title=target_title,
            experience_summary=experience_summary,
            resume_text=profile.get("resume_text"),
            job_title=job.title,
            job_description=job.description,
        )

        should_alert = evaluation.should_alert and evaluation.match_percentage >= threshold
        if not should_alert:
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

        alert_count += 1
        action: Literal["would_send", "sent", "skipped_low_match", "send_failed"]
        action = "would_send" if dry_run else "sent"
        error = None
        tailored_resume_path = None

        try:
            tailored_resume_path = generate_tailored_resume_txt(
                profile=profile,
                job=job,
                evaluation=evaluation,
            )
        except Exception as exc:
            logger.exception("Failed to generate tailored resume for %s", job.job_id)
            error = f"resume_generation_failed: {exc}"

        if not dry_run:
            try:
                alert_text = _format_job_alert(job, evaluation)
                if tailored_resume_path:
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
            )
        )

    return UserJobRunResult(
        whatsapp_number=whatsapp_number,
        query=target_title,
        scraped_count=scraped.job_count,
        duplicate_count=len(duplicate_ids),
        evaluated_count=len(fresh_jobs),
        alert_count=alert_count,
        dry_run=dry_run,
        results=results,
    )
