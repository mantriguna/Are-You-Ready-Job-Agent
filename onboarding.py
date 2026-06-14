from dataclasses import dataclass


@dataclass(frozen=True)
class OnboardingStep:
    profile_updates: dict
    reply: str
    document_path: str | None = None


def build_onboarding_step(profile: dict | None, incoming_text: str) -> OnboardingStep:
    text = " ".join(incoming_text.split())
    state = (profile or {}).get("onboarding_state", "new")

    if text.lower() == "reset":
        return OnboardingStep(
            profile_updates={
                "user_name": None,
                "target_title": None,
                "experience_summary": None,
                "resume_text": None,
                "onboarding_state": "awaiting_name",
            },
            reply="Profile setup restarted. What is your name?",
        )

    if state == "awaiting_name":
        return OnboardingStep(
            profile_updates={"user_name": text, "onboarding_state": "awaiting_target_title"},
            reply=f"Thanks, {text}. What job title should I search for?",
        )

    if state == "awaiting_target_title":
        return OnboardingStep(
            profile_updates={"target_title": text, "onboarding_state": "awaiting_experience"},
            reply=(
                "Got it. Send a short experience summary, for example: "
                "2 years Python backend developer with FastAPI and PostgreSQL."
            ),
        )

    if state == "awaiting_experience":
        return OnboardingStep(
            profile_updates={
                "experience_summary": text,
                "onboarding_state": "ready_for_resume",
            },
            reply=(
                "Profile saved. Next we will add your resume upload so I can match "
                "jobs more accurately. Send RESET if you want to restart setup."
            ),
        )

    if state == "ready_for_resume":
        return OnboardingStep(
            profile_updates={},
            reply=(
                "Your profile is ready for the resume step. Resume upload is the "
                "next feature we are wiring in. Send RESET to restart setup."
            ),
        )

    return OnboardingStep(
        profile_updates={"onboarding_state": "awaiting_name"},
        reply="Welcome to Are You Ready Job Agent. What is your name?",
    )
