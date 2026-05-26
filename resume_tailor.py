import os
from pathlib import Path
from re import sub

from google import genai
from google.genai import types

from ai_engine import JobMatchEvaluation
from job_scraper import JobListing


GENERATED_RESUME_DIR = Path("generated_resumes")


def _safe_filename(value: str) -> str:
    return sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-")[:100]


def _candidate_context(profile: dict) -> str:
    return f"""
Name: Guna Mantri
Phone: +918790431602
Email: gunamantri1602@gmail.com
Location: Srikakulam, Andhra Pradesh, India
LinkedIn: http://www.linkedin.com/in/mantri-guna
GitHub: https://github.com/mantriguna
Current role: Associate Software Engineer, Tech Mahindra, Feb 2025-Present, Hyderabad
Previous role: Software Engineer Trainee, Revature, Aug 2024-Dec 2024, Chennai
Target title: {profile.get("target_title")}
Experience summary: {profile.get("experience_summary")}
Core skills: Python, FastAPI, REST APIs, SQL, Docker, Git, Linux, Java, Spring Boot, AWS, Microservices, Jenkins, Kubernetes, Unit Testing, DSA
Projects: DSA Visualizer Suite; RevShop E-commerce Platform
Achievements: AWS Cloud Practitioner, DSA certification, 1000+ DSA problems, Top 25 GFG weekly contest
Education: B.Tech Computer Science, Vasireddy Venkatadri Institute of Technology, 2021-2024
""".strip()


def generate_tailored_resume_txt(
    *,
    profile: dict,
    job: JobListing,
    evaluation: JobMatchEvaluation,
) -> Path:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("Missing GEMINI_API_KEY environment variable.")

    prompt = f"""
Create a complete one-page ATS-friendly LaTeX resume for this candidate tailored to the job.
Rules:
- Return only LaTeX code. No markdown fences.
- Do not invent employers, degrees, dates, certifications, metrics, or tools.
- Keep the language natural and human-written. Avoid buzzwords and exaggerated claims.
- Emphasize truthful overlap with the job description.
- Keep the same basic Jake Gutierrez-style LaTeX structure: heading, Experience, Technical Skills, Projects, Certifications & Achievements, Education.
- Make it suitable for a 0-2 years backend/software role in India.

Candidate:
{_candidate_context(profile)}

Job:
Title: {job.title}
Company: {job.company}
Location: {job.location}
URL: {job.url}
Description:
{job.description[:8000]}

Match notes:
Matched skills: {", ".join(evaluation.matched_skills)}
Missing skills to avoid overclaiming: {", ".join(evaluation.missing_skills)}
""".strip()

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=os.getenv("GEMINI_FALLBACK_MODEL", "gemini-2.5-flash-lite"),
        contents=prompt,
        config=types.GenerateContentConfig(temperature=0.2),
    )

    latex_code = (response.text or "").strip()
    if latex_code.startswith("```"):
        latex_code = latex_code.strip("`")
        latex_code = latex_code.removeprefix("latex").strip()

    GENERATED_RESUME_DIR.mkdir(exist_ok=True)
    filename = f"{_safe_filename(job.company)}-{_safe_filename(job.title)}-{_safe_filename(job.job_id)}.txt"
    path = GENERATED_RESUME_DIR / filename
    path.write_text(latex_code, encoding="utf-8")
    return path
