import asyncio
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from database import get_ready_user_profiles
from matching_pipeline import UserJobRunResult, run_user_job_search
from whatsapp import send_text_message


class ScheduledRunResult(BaseModel):
    timezone: str
    current_hour: int
    matched_profile_count: int
    dry_run: bool
    runs: list[UserJobRunResult]
    errors: list[dict[str, str]]


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
    threshold: int = 75,
    override_hour: int | None = None,
    preferred_filters: bool = True,
    recent_days: int | None = 1,
    send_no_results: bool | None = None,
) -> ScheduledRunResult:
    timezone_name, current_hour, profiles = get_profiles_for_current_hour(
        override_hour=override_hour
    )
    max_concurrency = int(os.getenv("SCHEDULER_MAX_CONCURRENCY", "3"))
    semaphore = asyncio.Semaphore(max_concurrency)
    runs: list[UserJobRunResult] = []
    errors: list[dict[str, str]] = []

    async def run_one(profile: dict) -> None:
        async with semaphore:
            whatsapp_number = profile["whatsapp_number"]
            try:
                run_result = await run_user_job_search(
                    whatsapp_number=whatsapp_number,
                    limit=limit,
                    threshold=threshold,
                    dry_run=dry_run,
                    preferred_filters=preferred_filters,
                    recent_days=recent_days,
                )
                runs.append(run_result)

                should_send_no_results = (
                    send_no_results
                    if send_no_results is not None
                    else os.getenv("SEND_NO_RESULT_SUMMARY", "true").lower() == "true"
                )
                if not dry_run and should_send_no_results and run_result.alert_count == 0:
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

    return ScheduledRunResult(
        timezone=timezone_name,
        current_hour=current_hour,
        matched_profile_count=len(profiles),
        dry_run=dry_run,
        runs=runs,
        errors=errors,
    )
