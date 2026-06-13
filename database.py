import os
from datetime import UTC, datetime, timedelta

from supabase import Client, create_client


def get_supabase_client() -> Client:
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_server_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv(
        "SUPABASE_SECRET_KEY"
    )

    if not supabase_url or not supabase_server_key:
        raise RuntimeError(
            "Missing SUPABASE_URL and a SUPABASE_SECRET_KEY or "
            "SUPABASE_SERVICE_ROLE_KEY environment variable."
        )

    return create_client(supabase_url, supabase_server_key)


def get_user_profile(whatsapp_number: str) -> dict | None:
    result = (
        get_supabase_client()
        .table("user_profiles")
        .select("*")
        .eq("whatsapp_number", whatsapp_number)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


def save_user_profile(whatsapp_number: str, values: dict) -> dict:
    payload = {"whatsapp_number": whatsapp_number, **values}
    result = (
        get_supabase_client()
        .table("user_profiles")
        .upsert(payload, on_conflict="whatsapp_number")
        .execute()
    )
    return result.data[0]


def get_ready_user_profiles() -> list[dict]:
    result = (
        get_supabase_client()
        .table("user_profiles")
        .select("*")
        .in_("onboarding_state", ["ready_for_resume", "completed"])
        .not_.is_("target_title", "null")
        .not_.is_("experience_summary", "null")
        .execute()
    )
    return result.data


def get_sent_job_ids(whatsapp_number: str, job_ids: list[str]) -> set[str]:
    if not job_ids:
        return set()

    result = (
        get_supabase_client()
        .table("sent_jobs")
        .select("job_id")
        .eq("whatsapp_number", whatsapp_number)
        .in_("job_id", job_ids)
        .execute()
    )
    return {row["job_id"] for row in result.data}


def cleanup_old_sent_jobs(days: int = 60) -> None:
    cutoff = datetime.now(UTC) - timedelta(days=days)
    (
        get_supabase_client()
        .table("sent_jobs")
        .delete()
        .lt("sent_at", cutoff.isoformat())
        .execute()
    )


def save_sent_job(
    *,
    whatsapp_number: str,
    job_id: str,
    job_title: str,
    company_name: str,
    job_url: str,
    match_percentage: int,
) -> None:
    payload = {
        "whatsapp_number": whatsapp_number,
        "job_id": job_id,
        "job_title": job_title,
        "company_name": company_name,
        "job_url": job_url,
        "match_percentage": match_percentage,
    }
    (
        get_supabase_client()
        .table("sent_jobs")
        .upsert(payload, on_conflict="whatsapp_number,job_id")
        .execute()
    )


def replace_latest_job_alerts(whatsapp_number: str, jobs: list[dict]) -> None:
    supabase = get_supabase_client()
    supabase.table("latest_job_alerts").delete().eq(
        "whatsapp_number", whatsapp_number
    ).execute()

    if not jobs:
        return

    now = datetime.now(UTC).isoformat()
    payload = [
        {
            "whatsapp_number": whatsapp_number,
            "job_number": job["job_number"],
            "job_id": job["job_id"],
            "title": job["title"],
            "company": job["company"],
            "location": job.get("location"),
            "job_url": job["job_url"],
            "description": job.get("description", ""),
            "match_percentage": job.get("match_percentage"),
            "evaluation": job.get("evaluation", {}),
            "resume_file": job.get("resume_file"),
            "created_at": now,
        }
        for job in jobs
    ]
    supabase.table("latest_job_alerts").insert(payload).execute()


def get_latest_job_alert(whatsapp_number: str, job_number: int) -> dict | None:
    result = (
        get_supabase_client()
        .table("latest_job_alerts")
        .select("*")
        .eq("whatsapp_number", whatsapp_number)
        .eq("job_number", job_number)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None
