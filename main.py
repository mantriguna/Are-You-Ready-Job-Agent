import logging
import os

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
from pydantic import BaseModel, Field

from ai_engine import JobMatchEvaluation, evaluate_job_match
from database import get_supabase_client, get_user_profile, save_user_profile
from job_scraper import JobSearchResult, fetch_jobs
from matching_pipeline import UserJobRunResult, run_user_job_search
from onboarding import build_onboarding_step
from scheduler import ScheduledRunResult, run_scheduled_job_search
from whatsapp import extract_text_messages, send_text_message


load_dotenv()

app = FastAPI(title="AI Job Agent Backend")
app.mount("/generated-resumes", StaticFiles(directory="generated_resumes", check_dir=False), name="generated-resumes")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ai-job-agent")

VERIFY_TOKEN = os.getenv("META_VERIFY_TOKEN", "MySuperSecretToken123")


class JobMatchRequest(BaseModel):
    whatsapp_number: str
    job_title: str = Field(min_length=1)
    job_description: str = Field(min_length=1)


@app.get("/webhook")
async def verify_webhook(
    hub_mode: str | None = Query(None, alias="hub.mode"),
    hub_challenge: str | None = Query(None, alias="hub.challenge"),
    hub_verify_token: str | None = Query(None, alias="hub.verify_token"),
):
    """Handle Meta's webhook verification challenge."""
    if hub_mode == "subscribe" and hub_verify_token == VERIFY_TOKEN:
        logger.info("Meta webhook verification successful.")
        return Response(content=hub_challenge or "", media_type="text/plain")

    logger.warning("Webhook verification failed. Check META_VERIFY_TOKEN.")
    return Response(content="Verification token mismatch", status_code=403)


@app.post("/webhook")
async def receive_whatsapp_message(request: Request):
    """Receive incoming WhatsApp webhook events."""
    payload = await request.json()
    logger.info("Received WhatsApp webhook payload: %s", payload)

    for message in extract_text_messages(payload):
        profile = get_user_profile(message.whatsapp_number)
        onboarding_step = build_onboarding_step(profile, message.text)
        save_user_profile(message.whatsapp_number, onboarding_step.profile_updates)
        await send_text_message(message.whatsapp_number, onboarding_step.reply)

    return {"status": "SUCCESS"}


@app.get("/")
async def health_check():
    return {"status": "AI Job Agent backend is running"}


@app.get("/health/db")
async def database_health_check():
    supabase = get_supabase_client()
    result = supabase.table("user_profiles").select("whatsapp_number").limit(1).execute()
    return {"status": "database connected", "sample_count": len(result.data)}


@app.post("/ai/evaluate-job", response_model=JobMatchEvaluation)
async def evaluate_job(request: JobMatchRequest):
    profile = get_user_profile(request.whatsapp_number)
    if not profile:
        raise HTTPException(status_code=404, detail="WhatsApp profile not found.")

    if not profile.get("target_title") or not profile.get("experience_summary"):
        raise HTTPException(status_code=409, detail="WhatsApp profile is incomplete.")

    return evaluate_job_match(
        target_title=profile["target_title"],
        experience_summary=profile["experience_summary"],
        resume_text=profile.get("resume_text"),
        job_title=request.job_title,
        job_description=request.job_description,
    )


@app.get("/jobs/search", response_model=JobSearchResult)
async def search_jobs(
    query: str | None = None,
    location: str | None = None,
    limit: int = Query(25, ge=1, le=100),
):
    return await fetch_jobs(query=query, location=location, limit=limit)


@app.post("/jobs/run-user/{whatsapp_number}", response_model=UserJobRunResult)
async def run_jobs_for_user(
    whatsapp_number: str,
    limit: int = Query(5, ge=1, le=25),
    threshold: int = Query(75, ge=0, le=100),
    dry_run: bool = True,
    preferred_filters: bool = True,
    recent_days: int | None = Query(1, ge=0, le=30),
    ignore_duplicates: bool = False,
    use_template_alert: bool = False,
):
    try:
        return await run_user_job_search(
            whatsapp_number=whatsapp_number,
            limit=limit,
            threshold=threshold,
            dry_run=dry_run,
            preferred_filters=preferred_filters,
            recent_days=recent_days,
            ignore_duplicates=ignore_duplicates,
            use_template_alert=use_template_alert,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.api_route("/execute-daily-search", methods=["GET", "POST"], response_model=ScheduledRunResult)
async def execute_daily_search(
    token: str | None = None,
    dry_run: bool = False,
    limit: int = Query(5, ge=1, le=25),
    threshold: int = Query(75, ge=0, le=100),
    override_hour: int | None = Query(None, ge=0, le=23),
    preferred_filters: bool = True,
    recent_days: int | None = Query(1, ge=0, le=30),
    ignore_duplicates: bool = False,
    use_template_alert: bool | None = None,
    send_no_results: bool | None = None,
):
    cron_secret = os.getenv("CRON_SECRET")
    if cron_secret and token != cron_secret:
        raise HTTPException(status_code=403, detail="Invalid cron token.")

    return await run_scheduled_job_search(
        dry_run=dry_run,
        limit=limit,
        threshold=threshold,
        override_hour=override_hour,
        preferred_filters=preferred_filters,
        recent_days=recent_days,
        ignore_duplicates=ignore_duplicates,
        use_template_alert=use_template_alert,
        send_no_results=send_no_results,
    )
