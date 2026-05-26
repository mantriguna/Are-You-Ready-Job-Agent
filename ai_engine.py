import os

from google import genai
from google.genai import types
from google.genai.errors import ServerError
from pydantic import BaseModel, Field


class JobMatchEvaluation(BaseModel):
    match_percentage: int = Field(ge=0, le=100)
    matched_skills: list[str]
    missing_skills: list[str]
    short_reason: str = Field(max_length=280)
    should_alert: bool


def get_gemini_client() -> genai.Client:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("Missing GEMINI_API_KEY environment variable.")

    return genai.Client(api_key=api_key)


def evaluate_job_match(
    *,
    target_title: str,
    experience_summary: str,
    job_title: str,
    job_description: str,
    resume_text: str | None = None,
) -> JobMatchEvaluation:
    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    candidate_context = resume_text or experience_summary
    prompt = f"""
You are a narrow job-matching evaluator for a WhatsApp job alert service.
Score the candidate against the job from 0 to 100.
Alert only when the role is plausibly relevant and the score is at least 75.
Do not invent candidate skills that are not in the candidate context.

Target title:
{target_title}

Candidate context:
{candidate_context}

Job title:
{job_title}

Job description:
{job_description}
""".strip()

    client = get_gemini_client()
    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=JobMatchEvaluation,
        temperature=0.1,
    )

    try:
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=config,
        )
    except ServerError as error:
        fallback_model = os.getenv("GEMINI_FALLBACK_MODEL", "gemini-2.5-flash-lite")
        if error.code != 503 or model == fallback_model:
            raise

        response = client.models.generate_content(
            model=fallback_model,
            contents=prompt,
            config=config,
        )

    if response.parsed is None:
        raise RuntimeError("Gemini did not return a parsed job match evaluation.")

    return JobMatchEvaluation.model_validate(response.parsed)
