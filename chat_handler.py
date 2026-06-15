import re

from ai_engine import JobMatchEvaluation
from database import get_latest_job_alert, save_user_profile
from job_scraper import JobListing
from onboarding import OnboardingStep, build_onboarding_step
from resume_tailor import generate_tailored_resume_txt


PROFILE_FIELDS = {
    "1": ("user_name", "name"),
    "2": ("target_title", "target job titles"),
    "3": ("experience_summary", "experience summary"),
    "4": ("resume_text", "resume LaTeX/text"),
    "5": ("alert_time", "alert time, for example 20:00:00"),
}


def _menu() -> str:
    return (
        "Hi Guna. Your job agent is ready.\n\n"
        "Reply with one option:\n"
        "1. CONTINUE - keep current profile\n"
        "2. EDIT profile\n"
        "3. RESET profile\n"
        "4. job 1 details\n"
        "5. job 1 resume\n\n"
        "For any alert, use: job 11 details or job 11 resume."
    )


def _profile_edit_menu() -> str:
    return (
        "Which profile value do you want to edit?\n"
        "1. Name\n"
        "2. Target job titles\n"
        "3. Experience summary\n"
        "4. Resume LaTeX/text\n"
        "5. Alert time\n\n"
        "Reply with the number, or CONTINUE to leave it unchanged."
    )


def _is_greeting(text: str) -> bool:
    normalized = text.strip().lower()
    greetings = {
        "hi",
        "hello",
        "hey",
        "start",
        "menu",
        "tinava ra",
        "khana khaya",
        "khana khaya?",
    }
    return normalized in greetings


def _is_leave(text: str) -> bool:
    return text.strip().lower() in {"continue", "skip", "leave", "no", "cancel"}


def _is_goodbye(text: str) -> bool:
    normalized = text.strip().lower().replace("'", "")
    goodbyes = {
        "bye",
        "by",
        "goodbye",
        "good bye",
        "see you",
        "see you later",
        "im leaving",
        "i am leaving",
        "leaving",
        "talk later",
        "ok bye",
        "thanks bye",
    }
    return normalized in goodbyes


def _short_job_description(description: str) -> str:
    clean = " ".join(description.split())
    return clean[:1200] + ("..." if len(clean) > 1200 else "")


def _job_from_alert(alert: dict) -> JobListing:
    return JobListing(
        job_id=alert["job_id"],
        title=alert["title"],
        company=alert["company"],
        location=alert.get("location"),
        description=alert.get("description") or "",
        url=alert["job_url"],
        source="latest_job_alerts",
    )


def _evaluation_from_alert(alert: dict) -> JobMatchEvaluation:
    data = alert.get("evaluation") or {}
    return JobMatchEvaluation(
        match_percentage=alert.get("match_percentage") or data.get("match_percentage") or 0,
        matched_skills=data.get("matched_skills") or [],
        missing_skills=data.get("missing_skills") or [],
        short_reason=data.get("short_reason") or "Saved from the latest job alert.",
        should_alert=True,
    )


def build_chat_reply(profile: dict | None, incoming_text: str) -> OnboardingStep:
    text = " ".join(incoming_text.split())
    lower = text.lower()
    state = (profile or {}).get("onboarding_state", "new")

    if _is_goodbye(text):
        name = (profile or {}).get("user_name") or "there"
        return OnboardingStep(
            {},
            (
                f"Sure, {name}. I will keep watching for strong job matches and message you "
                "when the next alert is ready. Come back anytime."
            ),
        )

    job_match = re.search(r"\bjob\s*(\d+)\b(?:\s*[:\-]?\s*(.*))?", lower)
    if job_match and profile:
        job_number = int(job_match.group(1))
        intent = (job_match.group(2) or "details").strip()
        alert = get_latest_job_alert(profile["whatsapp_number"], job_number)
        if not alert:
            return OnboardingStep(
                {},
                (
                    f"I do not have Job {job_number} in your latest alert list yet. "
                    "After the 8 PM alert, ask again like: job 1 details or job 1 resume."
                ),
            )

        if any(word in intent for word in ["resume", "tailor", "latex"]):
            path = generate_tailored_resume_txt(
                profile=profile,
                job=_job_from_alert(alert),
                evaluation=_evaluation_from_alert(alert),
            )
            latex_code = path.read_text(encoding="utf-8")
            return OnboardingStep(
                {},
                (
                    f"For Job {job_number}, this is the tailored resume LaTeX code.\n\n"
                    f"{latex_code[:3500]}"
                ),
                str(path),
            )

        if any(word in intent for word in ["minimum", "experience", "min"]):
            description = (alert.get("description") or "").lower()
            years = re.findall(r"(\d+\+?\s*years?)", description)
            answer = ", ".join(sorted(set(years))) if years else "Not clearly mentioned."
            return OnboardingStep({}, f"Job {job_number} minimum experience: {answer}")

        return OnboardingStep(
            {},
            (
                f"Job {job_number}: {alert['title']}\n"
                f"Company: {alert['company']}\n"
                f"Location: {alert.get('location') or 'Not specified'}\n"
                f"Match: {alert.get('match_percentage')}%\n"
                f"Apply: {alert['job_url']}\n\n"
                f"Details: {_short_job_description(alert.get('description') or '')}\n\n"
                f"Reply job {job_number} resume for tailored LaTeX."
            ),
        )

    if profile and _is_greeting(text):
        return OnboardingStep({}, _menu())

    if lower in {"edit", "edit profile", "profile"} and profile:
        return OnboardingStep({"onboarding_state": "editing_profile"}, _profile_edit_menu())

    if lower in {"reset", "reset profile"} and profile:
        return OnboardingStep(
            {"onboarding_state": "confirm_reset"},
            "Are you sure you want to reset your profile? Reply YES to reset or CONTINUE to keep it.",
        )

    if state == "confirm_reset":
        if lower == "yes":
            return OnboardingStep(
                {
                    "user_name": None,
                    "target_title": None,
                    "experience_summary": None,
                    "resume_text": None,
                    "onboarding_state": "awaiting_name",
                },
                "Profile reset confirmed. What is your name?",
            )
        return OnboardingStep({"onboarding_state": "completed"}, "Profile kept unchanged.")

    if state == "editing_profile":
        if _is_leave(text):
            return OnboardingStep({"onboarding_state": "completed"}, "Continuing with your current profile.")
        field = PROFILE_FIELDS.get(lower)
        if not field:
            return OnboardingStep({}, _profile_edit_menu())
        field_name, label = field
        return OnboardingStep(
            {"onboarding_state": f"editing_{field_name}"},
            f"Send the new {label}, or type CONTINUE to leave it unchanged.",
        )

    if state.startswith("editing_"):
        if _is_leave(text):
            return OnboardingStep({"onboarding_state": "completed"}, "No change made. Continuing with current profile.")
        field_name = state.removeprefix("editing_")
        if field_name not in {field[0] for field in PROFILE_FIELDS.values()}:
            return OnboardingStep({"onboarding_state": "completed"}, _menu())
        save_value = text
        if field_name == "alert_time" and re.fullmatch(r"\d{1,2}", text):
            save_value = f"{int(text):02d}:00:00"
        return OnboardingStep(
            {field_name: save_value, "onboarding_state": "completed"},
            (
                f"Saved {field_name}. Is this correct? Reply EDIT profile to change another value, "
                "or CONTINUE to keep searching jobs."
            ),
        )

    if not profile or state in {"new", "awaiting_name", "awaiting_target_title", "awaiting_experience"}:
        return build_onboarding_step(profile, text)

    return OnboardingStep(
        {},
        (
            "I can help only with job search, job details, profile edits, and tailored resumes.\n\n"
            "Try: job 1 details, job 1 resume, EDIT profile, RESET profile, or CONTINUE."
        ),
    )
