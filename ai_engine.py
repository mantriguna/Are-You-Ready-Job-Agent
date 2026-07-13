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
        "hibernate",
        "jpa",
        "mysql",
        "react",
        "prometheus",
        "junit",
        "mockito",
        "system design",
        "retrieval-augmented generation",
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
            "platform engineer",
            "cloud engineer",
            "site reliability",
            "application developer",
            "member of technical staff",
        ]
    )
    title_text = job_title.lower()
    required_years = [int(value) for value in re.findall(r"(\d+)\+?\s*years?", job_text)]
    min_years = min(required_years) if required_years else None
    preferred_location = any(
        location in job_text
        for location in [
            "hyderabad",
            "bengaluru",
            "bangalore",
            "chennai",
            "pune",
            "gurugram",
            "gurgaon",
            "noida",
            "mumbai",
            "remote",
            "india",
        ]
    )
    senior_negative = any(
        marker in title_text or marker in job_text
        for marker in [
            "senior manager",
            "staff engineer",
            "principal",
            "architect",
            "director",
            "people manager",
            "5+ years",
            "6+ years",
            "7+ years",
            "8+ years",
            "10+ years",
        ]
    )
    non_software_negative = any(
        marker in title_text
        for marker in [
            "sales",
            "recruiter",
            "marketing",
            "finance",
            "customer support",
            "business analyst",
            "operations",
        ]
    )

    technical_score = min(35, len(matched) * 4)
    title_score = 20 if role_match else 0
    if any(term in title_text for term in ["backend", "sde", "software development engineer"]):
        title_score = min(20, title_score + 5)
    experience_score = 15
    if min_years is not None:
        if min_years <= 2:
            experience_score = 15
        elif min_years <= 4:
            experience_score = 10
        else:
            experience_score = 0
    location_score = 10 if preferred_location else 0
    education_score = 5 if any(term in job_text for term in ["computer science", "bachelor", "b.tech", "engineering"]) else 3
    domain_score = 5 if any(term in job_text for term in ["ai", "llm", "rag", "ecommerce", "distributed", "platform"]) else 2
    devops_score = 5 if any(term in job_text for term in ["aws", "docker", "kubernetes", "jenkins", "ci/cd", "linux"]) else 0
    recency_score = 5
    score = technical_score + title_score + experience_score + location_score + education_score + domain_score + devops_score + recency_score
    if senior_negative:
        score -= 30
    if non_software_negative:
        score -= 40
    score = max(0, min(100, score))
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
            "Deterministic score based on skill overlap, role relevance, experience, "
            "location, education, domain, DevOps signals, and seniority risk."
        ),
        should_alert=score >= int(os.getenv("MIN_MATCH_SCORE", "75")),
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
    deterministic_evaluation = _heuristic_job_match(
        target_title=target_title,
        candidate_context=resume_text or experience_summary,
        job_title=job_title,
        job_description=job_description,
    )
    if os.getenv("USE_LLM_MATCHING", "false").lower() != "true":
        return deterministic_evaluation

    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
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
        return deterministic_evaluation

    llm_evaluation = _parse_evaluation_response(response)
    return llm_evaluation.model_copy(
        update={
            "match_percentage": deterministic_evaluation.match_percentage,
            "should_alert": deterministic_evaluation.should_alert,
        }
    )
