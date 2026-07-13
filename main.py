import logging
import os
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
from pydantic import BaseModel, Field

from ai_engine import JobMatchEvaluation, evaluate_job_match
from chat_handler import build_chat_reply, is_latest_jobs_request
from database import (
    get_admin_status,
    get_supabase_client,
    get_user_profile,
    save_user_profile,
)
from job_scraper import JobSearchResult, fetch_jobs
from matching_pipeline import UserJobRunResult, run_user_job_search
from scheduler import (
    ScheduledRunResult,
    get_profiles_for_current_hour,
    run_scheduled_job_search,
)
from whatsapp import (
    extract_text_messages,
    mark_message_read_with_typing,
    send_document_message,
    send_template_message,
    send_text_message,
)


load_dotenv()

app = FastAPI(title="AI Job Agent Backend")
app.mount("/generated-resumes", StaticFiles(directory="generated_resumes", check_dir=False), name="generated-resumes")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ai-job-agent")

VERIFY_TOKEN = os.getenv("META_VERIFY_TOKEN", "MySuperSecretToken123")
WHATSAPP_TEXT_CHUNK_SIZE = 3500


class JobMatchRequest(BaseModel):
    whatsapp_number: str
    job_title: str = Field(min_length=1)
    job_description: str = Field(min_length=1)


def _mask_secret(value: str | None) -> str | None:
    if not value:
        return None
    if len(value) <= 10:
        return "***"
    return f"{value[:6]}...{value[-4:]}"


def _public_generated_file_url(path: str | None) -> str | None:
    if not path:
        return None
    base_url = os.getenv("PUBLIC_BASE_URL")
    if not base_url:
        return None
    filename = Path(path).name
    return f"{base_url.rstrip('/')}/generated-resumes/{filename}"


async def _run_latest_jobs_from_chat(whatsapp_number: str) -> None:
    try:
        logger.info("Starting on-demand latest job search for %s", whatsapp_number)
        result = await run_user_job_search(
            whatsapp_number=whatsapp_number,
            limit=int(os.getenv("CHAT_LATEST_JOB_LIMIT", "15")),
            threshold=int(os.getenv("CHAT_LATEST_JOB_THRESHOLD", "75")),
            dry_run=False,
            preferred_filters=True,
            recent_days=int(os.getenv("CHAT_LATEST_JOB_RECENT_DAYS", "1")),
            ignore_duplicates=False,
            use_template_alert=True,
            max_evaluations=int(os.getenv("CHAT_LATEST_JOB_MAX_EVALUATIONS", "25")),
        )
        sent_results = [
            item
            for item in result.results
            if item.action in {"sent", "sent_template"} and not item.error
        ]
        failed_results = [item for item in result.results if item.action == "send_failed"]
        logger.info(
            "Finished on-demand latest job search for %s: scraped=%s evaluated=%s alerts=%s sent=%s failed=%s",
            whatsapp_number,
            result.scraped_count,
            result.evaluated_count,
            result.alert_count,
            len(sent_results),
            len(failed_results),
        )

        if result.alert_count > 0 and sent_results:
            return

        if result.alert_count > 0 and failed_results:
            first_error = failed_results[0].error or "Unknown WhatsApp send error."
            await send_text_message(
                whatsapp_number,
                (
                    f"I found {result.alert_count} matching job(s), but WhatsApp could not "
                    f"send the summary template. Error: {first_error[:900]}"
                ),
            )
            return

        no_match_template = os.getenv("WHATSAPP_NO_MATCH_TEMPLATE_NAME")
        if no_match_template:
            await send_template_message(
                whatsapp_number=whatsapp_number,
                template_name=no_match_template,
                language_code=os.getenv("WHATSAPP_TEMPLATE_LANGUAGE", "en_US"),
                body_parameters=["the last 24 hours", "now"],
            )
            return

        await send_text_message(
            whatsapp_number,
            (
                "I checked jobs posted in the last 24 hours. No new non-duplicate "
                "matches passed your filters right now."
            ),
        )
    except Exception as exc:
        logger.exception("Failed to run latest jobs from chat for %s", whatsapp_number)
        await send_text_message(
            whatsapp_number,
            f"I could not complete the latest job check right now. Error: {exc}",
        )


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
async def receive_whatsapp_message(request: Request, background_tasks: BackgroundTasks):
    """Receive incoming WhatsApp webhook events."""
    payload = await request.json()
    logger.info("Received WhatsApp webhook payload: %s", payload)

    for message in extract_text_messages(payload):
        try:
            await mark_message_read_with_typing(message.message_id)
        except Exception as exc:
            logger.warning(
                "Could not send WhatsApp typing indicator for message %s: %s",
                message.message_id,
                exc,
            )

        try:
            profile = get_user_profile(message.whatsapp_number)
        except Exception as exc:
            logger.exception(
                "Database unavailable while handling WhatsApp message from %s",
                message.whatsapp_number,
            )
            await send_text_message(
                message.whatsapp_number,
                (
                    "I am online, but my database connection is unavailable right now. "
                    "Please check the Supabase project URL/key in Render, then message me again."
                ),
            )
            continue
        if profile and is_latest_jobs_request(message.text):
            await send_text_message(
                message.whatsapp_number,
                (
                    "Checking latest jobs from the last 24 hours now. I will send a "
                    "summary if new matches are found, or a no-match update if nothing new passes."
                ),
            )
            background_tasks.add_task(_run_latest_jobs_from_chat, message.whatsapp_number)
            continue

        chat_step = build_chat_reply(profile, message.text)
        if chat_step.profile_updates:
            save_user_profile(message.whatsapp_number, chat_step.profile_updates)
        document_url = _public_generated_file_url(chat_step.document_path)
        if document_url:
            await send_document_message(
                whatsapp_number=message.whatsapp_number,
                document_url=document_url,
                filename=Path(chat_step.document_path or "tailored_resume.txt").name,
                caption=chat_step.reply[:1024],
            )
            continue
        for start in range(0, len(chat_step.reply), WHATSAPP_TEXT_CHUNK_SIZE):
            await send_text_message(
                message.whatsapp_number,
                chat_step.reply[start : start + WHATSAPP_TEXT_CHUNK_SIZE],
            )

    return {"status": "SUCCESS"}


@app.get("/")
async def health_check():
    return {"status": "AI Job Agent backend is running"}


@app.get("/health/db")
async def database_health_check():
    try:
        supabase = get_supabase_client()
        result = supabase.table("user_profiles").select("whatsapp_number").limit(1).execute()
        return {"status": "database connected", "sample_count": len(result.data)}
    except Exception as exc:
        logger.exception("Database health check failed.")
        return JSONResponse(
            status_code=503,
            content={
                "status": "database unavailable",
                "error": str(exc)[:300],
            },
        )


@app.get("/health/meta")
async def meta_health_check(token: str | None = None):
    cron_secret = os.getenv("CRON_SECRET")
    if cron_secret and token != cron_secret:
        raise HTTPException(status_code=403, detail="Invalid health token.")

    return {
        "meta_access_token_present": bool(os.getenv("META_ACCESS_TOKEN")),
        "meta_access_token_preview": _mask_secret(os.getenv("META_ACCESS_TOKEN")),
        "meta_phone_number_id": os.getenv("META_PHONE_NUMBER_ID"),
        "meta_waba_id": os.getenv("META_WABA_ID"),
        "meta_graph_api_version": os.getenv("META_GRAPH_API_VERSION", "v25.0"),
        "template_name": os.getenv("WHATSAPP_JOB_TEMPLATE_NAME", "job_match_alert"),
        "template_language": os.getenv("WHATSAPP_TEMPLATE_LANGUAGE", "en_US"),
    }


@app.get("/admin/status")
async def admin_status(token: str | None = None):
    cron_secret = os.getenv("CRON_SECRET")
    if cron_secret and token != cron_secret:
        raise HTTPException(status_code=403, detail="Invalid admin token.")

    status = get_admin_status()
    status["integrations"] = {
        "gemini_configured": bool(os.getenv("GEMINI_API_KEY")),
        "meta_template_configured": bool(os.getenv("WHATSAPP_JOB_TEMPLATE_NAME")),
        "rapidapi_configured": bool(os.getenv("RAPIDAPI_KEY")),
        "daily_summary_template_configured": bool(
            os.getenv("WHATSAPP_DAILY_SUMMARY_TEMPLATE_NAME")
        ),
        "no_match_template_configured": bool(os.getenv("WHATSAPP_NO_MATCH_TEMPLATE_NAME")),
    }
    return status


@app.get("/test/job-template")
async def test_job_template(
    token: str | None = None,
    whatsapp_number: str = "918790431602",
):
    cron_secret = os.getenv("CRON_SECRET")
    if cron_secret and token != cron_secret:
        raise HTTPException(status_code=403, detail="Invalid test token.")

    try:
        result = await send_template_message(
            whatsapp_number=whatsapp_number,
            template_name=os.getenv("WHATSAPP_JOB_TEMPLATE_NAME", "job_match_alert"),
            language_code=os.getenv("WHATSAPP_TEMPLATE_LANGUAGE", "en_US"),
            body_parameters=[
                "Job 1: SDE-1 Contractual",
                "Amazon",
                "92%",
                "https://www.amazon.jobs/en/jobs/10428417/sde-1-contractual",
            ],
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return {"status": "template accepted by Meta", "meta_response": result}


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
    limit: int = Query(15, ge=1, le=50),
    threshold: int = Query(75, ge=0, le=100),
    dry_run: bool = True,
    preferred_filters: bool = True,
    recent_days: int | None = Query(1, ge=0, le=30),
    ignore_duplicates: bool = False,
    use_template_alert: bool = False,
    max_evaluations: int | None = Query(None, ge=1, le=50),
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
            max_evaluations=max_evaluations,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.api_route("/execute-daily-search", methods=["GET", "POST"], response_model=ScheduledRunResult)
async def execute_daily_search(
    background_tasks: BackgroundTasks,
    token: str | None = None,
    dry_run: bool = False,
    limit: int = Query(15, ge=1, le=50),
    threshold: int = Query(75, ge=0, le=100),
    override_hour: int | None = Query(None, ge=0, le=23),
    preferred_filters: bool = True,
    recent_days: int | None = Query(1, ge=0, le=30),
    ignore_duplicates: bool = False,
    use_template_alert: bool | None = None,
    send_no_results: bool | None = None,
    background: bool = False,
    max_evaluations: int | None = Query(None, ge=1, le=50),
):
    cron_secret = os.getenv("CRON_SECRET")
    if cron_secret and token != cron_secret:
        raise HTTPException(status_code=403, detail="Invalid cron token.")

    if background:
        timezone_name, current_hour, profiles = get_profiles_for_current_hour(
            override_hour=override_hour
        )
        background_tasks.add_task(
            run_scheduled_job_search,
            dry_run=dry_run,
            limit=limit,
            threshold=threshold,
            override_hour=override_hour,
            preferred_filters=preferred_filters,
            recent_days=recent_days,
            ignore_duplicates=ignore_duplicates,
            use_template_alert=use_template_alert,
            send_no_results=send_no_results,
            max_evaluations=max_evaluations,
        )
        return ScheduledRunResult(
            timezone=timezone_name,
            current_hour=current_hour,
            matched_profile_count=len(profiles),
            dry_run=dry_run,
            runs=[],
            errors=[],
        )

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
        max_evaluations=max_evaluations,
    )


@app.api_route("/cron/daily-whatsapp", methods=["GET", "POST"], response_model=ScheduledRunResult)
async def cron_daily_whatsapp(
    background_tasks: BackgroundTasks,
    token: str | None = None,
    limit: int = Query(15, ge=1, le=50),
    max_evaluations: int = Query(25, ge=1, le=50),
    threshold: int = Query(75, ge=0, le=100),
    recent_days: int = Query(1, ge=1, le=30),
    force: bool = False,
):
    cron_secret = os.getenv("CRON_SECRET")
    if cron_secret and token != cron_secret:
        raise HTTPException(status_code=403, detail="Invalid cron token.")

    override_hour = 20 if force else None
    try:
        timezone_name, current_hour, profiles = get_profiles_for_current_hour(
            override_hour=override_hour
        )
    except Exception as exc:
        logger.exception("Could not start daily WhatsApp cron because database is unavailable.")
        return ScheduledRunResult(
            timezone=os.getenv("APP_TIMEZONE", "Asia/Kolkata"),
            current_hour=20 if force else -1,
            matched_profile_count=0,
            dry_run=False,
            runs=[],
            errors=[{"whatsapp_number": "*", "error": f"Database unavailable: {exc}"}],
        )
    background_tasks.add_task(
        run_scheduled_job_search,
        dry_run=False,
        limit=limit,
        threshold=threshold,
        override_hour=override_hour,
        preferred_filters=True,
        recent_days=recent_days,
        ignore_duplicates=False,
        use_template_alert=True,
        send_no_results=True,
        max_evaluations=max_evaluations,
    )
    return ScheduledRunResult(
        timezone=timezone_name,
        current_hour=current_hour,
        matched_profile_count=len(profiles),
        dry_run=False,
        runs=[],
        errors=[],
    )
