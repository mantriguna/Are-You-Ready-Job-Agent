import json
import os
import re

from google import genai
from google.genai import types
from google.genai.errors import ClientError, ServerError
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


def _heuristic_job_match(
    *,
    target_title: str,
    candidate_context: str,
    job_title: str,
    job_description: str,
) -> JobMatchEvaluation:
    job_text = f"{job_title} {job_description}".lower()
    candidate_text = f"{target_title} {candidate_context}".lower()
    skill_terms = [
        "python",
        "java",
        "javascript",
        "sql",
        "fastapi",
        "spring boot",
        "docker",
        "kubernetes",
        "aws",
        "rest api",
        "microservices",
        "backend",
        "software engineer",
        "software development engineer",
        "sde",
        "rag",
        "llm",
        "ci/cd",
        "jenkins",
        "git",
        "linux",
        "data structures",
        "algorithms",
    ]
    matched = [
        term
        for term in skill_terms
        if term in candidate_text and term in job_text
    ]
    role_match = any(
        term in job_text
        for term in [
            "software engineer",
            "software development engineer",
            "backend",
            "python developer",
            "java developer",
            "sde",
        ]
    )
    score = min(95, 45 + len(matched) * 5 + (15 if role_match else 0))
    missing = [
        term
        for term in skill_terms
        if term not in candidate_text and term in job_text
    ][:6]
    return JobMatchEvaluation(
        match_percentage=score,
        matched_skills=matched[:12] or ["Role appears relevant to your target titles"],
        missing_skills=missing,
        short_reason=(
            "Gemini quota was unavailable, so this is a conservative local match "
            "based on overlapping role and skill terms."
        ),
        should_alert=score >= 70,
    )


def _should_try_fallback(error: Exception, model: str, fallback_model: str) -> bool:
    if model == fallback_model:
        return False
    code = getattr(error, "code", None)
    status_code = getattr(error, "status_code", None)
    return code in {429, 503} or status_code in {429, 503}


def evaluate_job_match(
    *,
    target_title: str,
    experience_summary: str,
    job_title: str,
    job_description: str,
    resume_text: str | None = None,
) -> JobMatchEvaluation:
    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite")
    fallback_model = os.getenv("GEMINI_FALLBACK_MODEL", "gemini-2.5-flash-lite")
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
        try:
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config=config,
            )
        except (ClientError, ServerError) as error:
            if not _should_try_fallback(error, model, fallback_model):
                raise
            response = client.models.generate_content(
                model=fallback_model,
                contents=prompt,
                config=config,
            )
    except Exception:
        if os.getenv("ENABLE_HEURISTIC_AI_FALLBACK", "true").lower() != "true":
            raise
        return _heuristic_job_match(
            target_title=target_title,
            candidate_context=candidate_context,
            job_title=job_title,
            job_description=job_description,
        )

    return _parse_evaluation_response(response)
