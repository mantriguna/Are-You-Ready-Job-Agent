import os
from pathlib import Path

from dotenv import load_dotenv

from database import get_ready_user_profiles, get_supabase_client


REQUIRED_ENV = [
    "META_ACCESS_TOKEN",
    "META_PHONE_NUMBER_ID",
    "META_VERIFY_TOKEN",
    "SUPABASE_URL",
    "GEMINI_API_KEY",
    "APP_TIMEZONE",
]


def _is_set(name: str) -> bool:
    return bool(os.getenv(name))


def main() -> int:
    load_dotenv()
    failures: list[str] = []
    warnings: list[str] = []

    for name in REQUIRED_ENV:
        if not _is_set(name):
            failures.append(f"Missing required env var: {name}")

    if not (_is_set("SUPABASE_SERVICE_ROLE_KEY") or _is_set("SUPABASE_SECRET_KEY")):
        failures.append("Missing Supabase backend key: SUPABASE_SERVICE_ROLE_KEY or SUPABASE_SECRET_KEY")

    if not _is_set("CRON_SECRET"):
        warnings.append("CRON_SECRET is not set. Production cron endpoint will be unprotected.")

    if not _is_set("PUBLIC_BASE_URL"):
        warnings.append("PUBLIC_BASE_URL is not set. WhatsApp resume document attachments will not use public links.")

    if os.getenv("ENABLE_AMAZON_JOBS", "true").lower() != "true":
        warnings.append("ENABLE_AMAZON_JOBS is not true. Amazon-focused search is disabled.")

    source_count = sum(
        1
        for name in ["GREENHOUSE_BOARD_TOKENS", "LEVER_COMPANY_SLUGS", "ASHBY_BOARD_NAMES"]
        if _is_set(name)
    )
    if source_count == 0:
        warnings.append("No Greenhouse/Lever/Ashby sources configured. Only Amazon will be searched.")

    Path("generated_resumes").mkdir(exist_ok=True)

    if not failures:
        try:
            get_supabase_client().table("user_profiles").select("whatsapp_number").limit(1).execute()
            profiles = get_ready_user_profiles()
            if not profiles:
                warnings.append("No ready user profiles found. Complete WhatsApp onboarding before scheduled runs.")
        except Exception as exc:
            failures.append(f"Supabase connection failed: {exc}")

    print("Preflight results")
    print("=================")
    if failures:
        print("FAILURES:")
        for failure in failures:
            print(f"- {failure}")
    else:
        print("No blocking failures.")

    if warnings:
        print("\nWARNINGS:")
        for warning in warnings:
            print(f"- {warning}")
    else:
        print("\nNo warnings.")

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
