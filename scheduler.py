import asyncio
import logging
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from database import (
    cleanup_old_sent_jobs,
    create_cron_run,
    finish_cron_run,
    get_ready_user_profiles,
)
from matching_pipeline import UserJobRunResult, run_user_job_search
from whatsapp import send_template_message, send_text_message

logger = logging.getLogger("ai-job-agent")


class ScheduledRunResult(BaseModel):
    timezone: str
    current_hour: int
    matched_profile_count: int
    dry_run: bool
    runs: list[UserJobRunResult]
    errors: list[dict[str, str]]


def _scheduled_error_result(
    *,
    timezone_name: str | None = None,
    current_hour: int = -1,
    dry_run: bool,
    error: Exception | str,
) -> ScheduledRunResult:
    return ScheduledRunResult(
        timezone=timezone_name or os.getenv("APP_TIMEZONE", "Asia/Kolkata"),
        current_hour=current_hour,
        matched_profile_count=0,
        dry_run=dry_run,
        runs=[],
        errors=[{"whatsapp_number": "*", "error": str(error)}],
    )


def _profile_alert_hour(profile: dict) -> int | None:
    alert_time = profile.get("alert_time")
    if not alert_time:
        return None

    if isinstance(alert_time, str):
        try:
            return int(alert_time.split(":")[0])
        except ValueError:
            return None

    return getattr(alert_time, "hour", None)


def get_profiles_for_current_hour(
    *,
    timezone_name: str | None = None,
    override_hour: int | None = None,
) -> tuple[str, int, list[dict]]:
    timezone_name = timezone_name or os.getenv("APP_TIMEZONE", "Asia/Kolkata")
    current_hour = (
        override_hour
        if override_hour is not None
        else datetime.now(ZoneInfo(timezone_name)).hour
    )

    profiles = [
        profile
        for profile in get_ready_user_profiles()
        if _profile_alert_hour(profile) == current_hour
    ]
    return timezone_name, current_hour, profiles


async def run_scheduled_job_search(
    *,
    dry_run: bool = False,
    limit: int = 5,
    threshold: int | None = None,
    min_match_score: int | None = None,
    override_hour: int | None = None,
    preferred_filters: bool = True,
    recent_days: int | None = 1,
    ignore_duplicates: bool = False,
    use_template_alert: bool | None = None,
    send_no_results: bool | None = None,
    max_evaluations: int | None = None,
    max_matched_jobs_per_user: int | None = None,
) -> ScheduledRunResult:
    try:
        timezone_name, current_hour, profiles = get_profiles_for_current_hour(
            override_hour=override_hour
        )
    except Exception as exc:
        logger.exception("Scheduled search could not read ready user profiles.")
        return _scheduled_error_result(
            current_hour=override_hour if override_hour is not None else -1,
            dry_run=dry_run,
            error=f"Database unavailable while loading profiles: {exc}",
        )

    max_concurrency = int(os.getenv("SCHEDULER_MAX_CONCURRENCY", "3"))
    semaphore = asyncio.Semaphore(max_concurrency)
    runs: list[UserJobRunResult] = []
    errors: list[dict[str, str]] = []
    try:
        run_id = create_cron_run(
            timezone=timezone_name,
            current_hour=current_hour,
            matched_profile_count=len(profiles),
            dry_run=dry_run,
        )
    except Exception as exc:
        logger.exception("Scheduled search could not create cron run log.")
        run_id = None
        errors.append({"whatsapp_number": "*", "error": f"Cron log unavailable: {exc}"})

    should_use_template_alert = (
        use_template_alert
        if use_template_alert is not None
        else os.getenv("USE_WHATSAPP_TEMPLATES", "true").lower() == "true"
    )
    cleanup_days = int(os.getenv("SENT_JOB_RETENTION_DAYS", "60"))
    try:
        cleanup_old_sent_jobs(cleanup_days)
    except Exception as exc:
        logger.warning("Could not clean old sent jobs: %s", exc)
        errors.append(
            {"whatsapp_number": "*", "error": f"Sent job cleanup unavailable: {exc}"}
        )

    if max_evaluations is None:
        max_evaluations = int(os.getenv("MAX_EVALUATIONS_PER_RUN", "0"))
    effective_threshold = (
        min_match_score
        if min_match_score is not None
        else threshold
    )

    async def run_one(profile: dict) -> None:
        async with semaphore:
            whatsapp_number = profile["whatsapp_number"]
            try:
                run_result = await run_user_job_search(
                    whatsapp_number=whatsapp_number,
                    limit=limit,
                    threshold=effective_threshold,
                    dry_run=dry_run,
                    preferred_filters=preferred_filters,
                    recent_days=recent_days,
                    ignore_duplicates=ignore_duplicates,
                    use_template_alert=should_use_template_alert,
                    max_evaluations=max_evaluations,
                    max_matched_jobs_per_user=max_matched_jobs_per_user,
                )
                runs.append(run_result)

                should_send_no_results = (
                    send_no_results
                    if send_no_results is not None
                    else os.getenv("SEND_NO_RESULT_SUMMARY", "false").lower() == "true"
                )
                if not dry_run and should_send_no_results and run_result.alert_count == 0:
                    if os.getenv("WHATSAPP_NO_MATCH_TEMPLATE_NAME"):
                        await send_template_message(
                            whatsapp_number=whatsapp_number,
                            template_name=os.getenv("WHATSAPP_NO_MATCH_TEMPLATE_NAME", ""),
                            language_code=os.getenv("WHATSAPP_TEMPLATE_LANGUAGE", "en_US"),
                            body_parameters=["today", "8 PM"],
                        )
                    else:
                        await send_text_message(
                            whatsapp_number,
                            (
                                "Job search completed for today: no India 0-2 years "
                                "1 lakh+/month matches passed the filter. I will check again at 8 PM tomorrow."
                            ),
                        )
            except Exception as exc:
                errors.append(
                    {"whatsapp_number": whatsapp_number, "error": str(exc)}
                )

    await asyncio.gather(*(run_one(profile) for profile in profiles))
    try:
        finish_cron_run(
            run_id,
            status="failed" if errors else "completed",
            jobs_scraped=sum(run.scraped_count for run in runs),
            jobs_sent=sum(run.alert_count for run in runs),
            errors=errors,
        )
    except Exception as exc:
        logger.warning("Could not finish cron run log: %s", exc)
        errors.append({"whatsapp_number": "*", "error": f"Cron finish unavailable: {exc}"})

    return ScheduledRunResult(
        timezone=timezone_name,
        current_hour=current_hour,
        matched_profile_count=len(profiles),
        dry_run=dry_run,
        runs=runs,
        errors=errors,
    )
