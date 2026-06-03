import json
import os
import re

from google import genai
from google.genai import types
from google.genai.errors import ServerError
from pydantic import BaseModel, Field


class JobMatchEvaluation(BaseModel):
    match_percentage: int = Field(ge=0, le=100)
    matched_skills: list[str]
    missing_skills: list[str]
    short_reason: str
    should_alert: bool


def _parse_evaluation_response(response: object) -> JobMatchEvaluation:
    parsed = getattr(response, "parsed", None)
    if parsed is not None:
        return _normalize_evaluation(JobMatchEvaluation.model_validate(parsed))

    text = (getattr(response, "text", None) or "").strip()
    if not text:
        raise RuntimeError("Gemini returned an empty job match evaluation.")

    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()

    try:
        return _normalize_evaluation(JobMatchEvaluation.model_validate_json(text))
    except Exception:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            raise RuntimeError("Gemini did not return JSON for job match evaluation.")
        return _normalize_evaluation(JobMatchEvaluation.model_validate(json.loads(match.group(0))))


def _normalize_evaluation(evaluation: JobMatchEvaluation) -> JobMatchEvaluation:
    if len(evaluation.short_reason) <= 280:
        return evaluation

    return evaluation.model_copy(
        update={"short_reason": evaluation.short_reason[:277].rstrip() + "..."}
    )


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

    return _parse_evaluation_response(response)
