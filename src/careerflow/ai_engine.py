"""
CareerFlow AI Engine — OpenRouter-powered intelligence layer.

Provides:
  - Candidate knowledge base loading and context assembly
  - Job-specific resume content generation (tailored headlines, summaries, bullets)
  - Intelligent questionnaire answering using candidate context
  - SEO-optimized Naukri headline generation
  - AI-powered job relevance scoring
"""

from __future__ import annotations

import json
import os
import logging
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# OpenRouter client (OpenAI-compatible)
# ---------------------------------------------------------------------------

_client = None


def _get_client():
    """Lazily initialise the OpenAI-compatible client pointed at OpenRouter."""
    global _client
    if _client is not None:
        return _client

    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        raise RuntimeError(
            "OPENROUTER_API_KEY environment variable is not set. "
            "Set it in your .env file or provide it via the dashboard."
        )

    from openai import OpenAI

    _client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=api_key,
        default_headers={
            "HTTP-Referer": "https://careerflow-ai.local",
            "X-Title": "CareerFlow AI",
        },
    )
    return _client


def reset_client():
    """Force re-creation of the client (e.g. after API key change)."""
    global _client
    _client = None


def get_default_model() -> str:
    return os.environ.get("OPENROUTER_MODEL", "google/gemini-2.0-flash-001")


# ---------------------------------------------------------------------------
# Candidate Knowledge Base
# ---------------------------------------------------------------------------

KNOWLEDGE_PATH = Path("config/candidate_knowledge.json")

_knowledge_cache: dict | None = None


def load_knowledge() -> dict:
    """Load and cache the candidate knowledge base from JSON."""
    global _knowledge_cache
    if _knowledge_cache is not None:
        return _knowledge_cache
    if not KNOWLEDGE_PATH.exists():
        logger.warning("Knowledge base not found at %s", KNOWLEDGE_PATH)
        return {}
    with open(KNOWLEDGE_PATH, "r", encoding="utf-8") as f:
        _knowledge_cache = json.load(f)
    return _knowledge_cache


def reload_knowledge():
    """Force reload the knowledge base."""
    global _knowledge_cache
    _knowledge_cache = None
    return load_knowledge()


def build_candidate_context() -> str:
    """Assemble a rich text prompt describing the candidate for AI calls."""
    kb = load_knowledge()
    if not kb:
        return "No candidate knowledge base loaded."

    identity = kb.get("identity", {})
    parts = [
        f"Candidate Name: {identity.get('name', 'Unknown')}",
        f"Role: {identity.get('role', 'Software Engineer')}",
        f"Experience: {identity.get('experience_years', 0)} years",
        f"Education: {identity.get('education', 'N/A')}",
        f"Current Status: {identity.get('current_status', 'Active')}",
        f"Notice Period: {identity.get('notice_period', 'N/A')}",
        "",
        f"Professional Summary: {kb.get('professional_summary', '')}",
        "",
    ]

    # Skills
    skills = kb.get("core_skills", {})
    if skills:
        parts.append("=== Core Skills ===")
        for category, skill_list in skills.items():
            parts.append(f"  {category}: {', '.join(skill_list)}")
        parts.append("")

    # GitHub Projects
    projects = kb.get("github_projects", [])
    if projects:
        parts.append("=== Key Projects ===")
        for proj in projects:
            if proj.get("name", "").startswith("ADD YOUR"):
                continue
            parts.append(f"  Project: {proj['name']}")
            parts.append(f"  Description: {proj.get('description', '')}")
            parts.append(f"  Tech Stack: {', '.join(proj.get('tech_stack', []))}")
            for hl in proj.get("highlights", []):
                parts.append(f"    • {hl}")
            parts.append("")

    # Work experience
    experience = kb.get("work_experience", [])
    if experience:
        parts.append("=== Work Experience ===")
        for exp in experience:
            if "YOUR COMPANY" in exp.get("company", ""):
                continue
            parts.append(f"  {exp.get('role', '')} at {exp.get('company', '')}")
            parts.append(f"  Duration: {exp.get('duration', '')}")
            for ach in exp.get("achievements", []):
                parts.append(f"    • {ach}")
            parts.append("")

    # Questionnaire defaults
    defaults = kb.get("questionnaire_defaults", {})
    if defaults:
        parts.append("=== Questionnaire Defaults ===")
        for key, value in defaults.items():
            parts.append(f"  {key}: {value}")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# AI-Powered Resume Content Generation
# ---------------------------------------------------------------------------

def generate_tailored_resume(
    job_title: str,
    company: str,
    job_description: str,
    model: str | None = None,
) -> dict:
    """
    Generate tailored resume content for a specific job posting.

    Returns a dict with keys:
      - headline: SEO-optimized headline for Naukri
      - summary: Tailored professional summary
      - experience_bullets: List of rewritten experience bullet points
      - matched_keywords: Keywords from the JD that match candidate skills
      - cover_note: Brief cover note / why-me paragraph
    """
    client = _get_client()
    model = model or get_default_model()
    context = build_candidate_context()

    system_prompt = """You are an expert career coach and ATS optimization specialist.
You help candidates tailor their resume content to specific job descriptions.

RULES:
1. Extract key skills and keywords from the job description
2. Match them against the candidate's actual skills and experience — NEVER fabricate experience
3. Rewrite resume content to naturally incorporate matched keywords
4. Use strong action verbs (Engineered, Architected, Optimized, Built, Designed)
5. Include metrics/numbers where possible
6. Keep the headline under 200 characters and keyword-rich
7. The summary should be 3-4 concise sentences
8. Generate 4-6 experience bullet points highlighting relevant work
9. Always respond in valid JSON format"""

    user_prompt = f"""Generate tailored resume content for this job application.

=== CANDIDATE PROFILE ===
{context}

=== TARGET JOB ===
Title: {job_title}
Company: {company}
Job Description:
{job_description}

=== REQUIRED OUTPUT FORMAT (JSON) ===
{{
  "headline": "Keyword-rich Naukri headline (under 200 chars)",
  "summary": "3-4 sentence professional summary tailored to this role",
  "experience_bullets": [
    "Achievement-focused bullet point 1 with metrics",
    "Achievement-focused bullet point 2 with metrics",
    "..."
  ],
  "matched_keywords": ["keyword1", "keyword2", "..."],
  "cover_note": "2-3 sentence personalized cover note for this specific role"
}}"""

    try:
        completion = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.7,
            max_tokens=1500,
        )
        raw = completion.choices[0].message.content.strip()
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.error("AI returned non-JSON response: %s", raw[:300])
        return {"error": "AI returned invalid JSON", "raw_response": raw[:500]}
    except Exception as e:
        logger.error("AI resume generation failed: %s", e)
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# AI-Powered Headline Optimizer
# ---------------------------------------------------------------------------

def generate_optimized_headline(
    target_role: str = "",
    current_headline: str = "",
    model: str | None = None,
) -> dict:
    """
    Generate an SEO-optimized Naukri headline.

    Returns dict with:
      - headline: The optimized headline
      - keywords: List of keywords included
      - reasoning: Why this headline works
    """
    client = _get_client()
    model = model or get_default_model()
    kb = load_knowledge()
    skills = kb.get("core_skills", {})
    identity = kb.get("identity", {})

    system_prompt = """You are a Naukri profile SEO specialist.
Generate a headline that maximizes recruiter search visibility.

RULES:
1. Format: [Role] | [Core Skill 1], [Core Skill 2], [Core Skill 3] | [Experience/Location]
2. Under 200 characters
3. Use exact terms recruiters search for (Python, Node.js, AWS, not "Programming")
4. Never use generic phrases like "Seeking Opportunities" or "Hardworking Professional"
5. Respond in valid JSON format"""

    user_prompt = f"""Generate an optimized Naukri headline.

Current headline: {current_headline or 'None'}
Target role: {target_role or identity.get('role', 'Backend Engineer')}
Experience: {identity.get('experience_years', 2)} years
Location: {', '.join(identity.get('preferred_locations', ['Bangalore']))}
Top Skills: {json.dumps(skills)}

=== REQUIRED OUTPUT FORMAT (JSON) ===
{{
  "headline": "The optimized headline (under 200 chars)",
  "keywords": ["keyword1", "keyword2"],
  "reasoning": "Brief explanation of why this headline ranks well"
}}"""

    try:
        completion = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.6,
            max_tokens=500,
        )
        raw = completion.choices[0].message.content.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"error": "AI returned invalid JSON", "raw_response": raw[:500]}
    except Exception as e:
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# AI-Powered Questionnaire Answering
# ---------------------------------------------------------------------------

def answer_questionnaire(
    questions: list[dict],
    job_title: str = "",
    company: str = "",
    model: str | None = None,
) -> dict:
    """
    Intelligently answer Naukri job application questionnaire questions.

    Args:
        questions: List of questionnaire dicts from Naukri API with keys:
            questionId, questionName, questionType, answerOption
        job_title: The job being applied to
        company: The company name

    Returns:
        Dict mapping questionId -> answer (string for text, [optionId] for options)
    """
    client = _get_client()
    model = model or get_default_model()
    context = build_candidate_context()
    kb = load_knowledge()
    defaults = kb.get("questionnaire_defaults", {})

    # Build a readable question list for the AI
    q_descriptions = []
    for q in questions:
        qid = q.get("questionId", "")
        qtext = q.get("questionName", "")
        qtype = q.get("questionType", "text box")
        options = q.get("answerOption", {})
        desc = f"Question ID: {qid}\n  Text: {qtext}\n  Type: {qtype}"
        if options:
            desc += "\n  Options:"
            for opt_id, opt_text in options.items():
                desc += f"\n    {opt_id}: {opt_text}"
        q_descriptions.append(desc)

    system_prompt = """You are an expert job application assistant.
Answer job application questionnaire questions based on the candidate's actual profile.

RULES:
1. For text box questions: provide a brief, honest, specific answer (numbers for experience/CTC)
2. For option/radio questions: select the BEST matching option ID
3. NEVER lie or fabricate experience — use the candidate's real data
4. For experience questions: use the candidate's actual years, rounded appropriately
5. For CTC questions: use the candidate's actual CTC or "0" for freshers
6. For yes/no skill questions: answer yes ONLY if the candidate genuinely has that skill
7. For notice period: use the candidate's actual notice period
8. Respond ONLY in the exact JSON format specified"""

    user_prompt = f"""Answer these job application questions for the candidate.

=== CANDIDATE PROFILE ===
{context}

=== DEFAULT ANSWERS FOR COMMON QUESTIONS ===
{json.dumps(defaults, indent=2)}

=== JOB CONTEXT ===
Job Title: {job_title}
Company: {company}

=== QUESTIONS TO ANSWER ===
{chr(10).join(q_descriptions)}

=== REQUIRED OUTPUT FORMAT (JSON) ===
Return a JSON object where each key is the questionId and the value is:
  - For "text box" questions: a string answer
  - For option/radio questions: a list containing the selected option ID, e.g. ["optionId"]

Example:
{{
  "q123": "2",
  "q456": ["opt_yes"],
  "q789": "Bangalore"
}}"""

    try:
        completion = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
            max_tokens=1000,
        )
        raw = completion.choices[0].message.content.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.error("AI questionnaire response not valid JSON: %s", raw[:300])
        # Fallback to static answers
        return _static_questionnaire_fallback(questions, defaults)
    except Exception as e:
        logger.error("AI questionnaire answering failed: %s", e)
        return _static_questionnaire_fallback(questions, defaults)


def _static_questionnaire_fallback(questions: list[dict], defaults: dict) -> dict:
    """Fallback to rule-based answering when AI is unavailable."""
    answers = {}
    for q in questions:
        qid = q["questionId"]
        qtext = (q.get("questionName") or "").lower()
        qtype = (q.get("questionType") or "").lower()
        options = q.get("answerOption") or {}

        if qtype == "text box":
            if "current ctc" in qtext or "current salary" in qtext:
                answers[qid] = defaults.get("current_ctc", "0")
            elif "expected ctc" in qtext or "expected salary" in qtext:
                answers[qid] = defaults.get("expected_ctc", "3")
            elif "notice" in qtext:
                answers[qid] = str(defaults.get("notice_period_days", 0))
            elif "experience" in qtext:
                if "python" in qtext:
                    answers[qid] = defaults.get("python_experience_years", "2")
                elif "node" in qtext:
                    answers[qid] = defaults.get("nodejs_experience_years", "2")
                elif "react" in qtext:
                    answers[qid] = defaults.get("react_experience_years", "1")
                elif "docker" in qtext:
                    answers[qid] = defaults.get("docker_experience_years", "1")
                else:
                    answers[qid] = str(defaults.get("total_experience_years", "2"))
            elif "location" in qtext or "city" in qtext:
                answers[qid] = defaults.get("preferred_location", "Bangalore")
            else:
                answers[qid] = str(defaults.get("total_experience_years", "2"))
        else:
            if options:
                # Prefer "yes" for skill / availability questions
                for k, v in options.items():
                    if "yes" in v.lower():
                        answers[qid] = [k]
                        break
                else:
                    # Prefer "immediate" for notice period questions
                    for k, v in options.items():
                        if "immediate" in v.lower():
                            answers[qid] = [k]
                            break
                    else:
                        answers[qid] = [list(options.keys())[0]]
            else:
                answers[qid] = "1"

    return answers


# ---------------------------------------------------------------------------
# AI Status Check
# ---------------------------------------------------------------------------

def get_ai_status() -> dict:
    """Return the current AI engine configuration status."""
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    model = get_default_model()
    kb = load_knowledge()
    has_knowledge = bool(kb and kb.get("identity", {}).get("name"))

    return {
        "api_key_configured": bool(api_key and api_key != "your_openrouter_api_key"),
        "api_key_preview": f"sk-...{api_key[-6:]}" if len(api_key) > 10 else "Not set",
        "model": model,
        "knowledge_base_loaded": has_knowledge,
        "candidate_name": kb.get("identity", {}).get("name", "Not configured"),
        "projects_count": len([
            p for p in kb.get("github_projects", [])
            if not p.get("name", "").startswith("ADD YOUR")
        ]),
        "skills_count": sum(
            len(v) for v in kb.get("core_skills", {}).values()
        ),
    }
