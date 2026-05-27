from __future__ import annotations

import csv
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from src.careerflow.config import resolve_workspace_path


INTERNSHIP_PLAN_FILE = Path("internship_plan.csv")
INTERNSHIP_APPLIED_FILE = Path("internship_applications.csv")


@dataclass
class ResumeProfile:
    id: str
    label: str
    path: Path
    keywords: list[str]


@dataclass
class InternshipMatch:
    job: Any
    score: int
    reason: str
    resume_profile: ResumeProfile
    keywords: list[str]


def load_resume_profiles(config: dict) -> list[ResumeProfile]:
    profiles = []
    for raw in config.get("resume_profiles", []):
        path = resolve_workspace_path(raw.get("path"))
        profiles.append(
            ResumeProfile(
                id=raw["id"],
                label=raw["label"],
                path=path,
                keywords=[_norm(term) for term in raw.get("keywords", []) if _norm(term)],
            )
        )
    if not profiles:
        raise ValueError("No resume_profiles configured")
    return profiles


def fetch_internship_jobs(job_client, config: dict) -> list:
    search = config.get("search", {})
    keywords = search.get("keywords", [])
    locations = search.get("locations", [""])
    experience_levels = search.get("experience_levels", [0])
    pages = int(search.get("pages", 1))
    job_age = int(search.get("job_age_days", 7))
    results_per_page = int(search.get("results_per_page", 20))
    delay_seconds = float(search.get("delay_seconds", 1.2))
    search_params = search.get("params", {})

    seen_ids: set[str] = set()
    jobs = []

    for keyword in keywords:
        for location in locations:
            for experience in experience_levels:
                for page in range(1, pages + 1):
                    result = job_client.search_jobs(
                        keyword=keyword,
                        location=location,
                        experience=experience,
                        job_age=job_age,
                        page=page,
                        results_per_page=results_per_page,
                        extra_params=search_params,
                    )
                    new_jobs = [job for job in result if job.job_id and job.job_id not in seen_ids]
                    for job in new_jobs:
                        seen_ids.add(job.job_id)
                    jobs.extend(new_jobs)
                    print(
                        f"[internship-fetch] {keyword} | {location or 'All India'} "
                        f"| exp={experience} | page={page}: {len(result)} fetched, {len(new_jobs)} new"
                    )
                    time.sleep(delay_seconds)
                    if not result:
                        break

    return jobs


def match_internships(jobs: list, config: dict) -> list[InternshipMatch]:
    profiles = load_resume_profiles(config)
    filters = config.get("filters", {})
    scoring = config.get("scoring", {})
    max_jobs = int(scoring.get("max_jobs_to_score", 250))
    matches = []

    for job in jobs[:max_jobs]:
        text = _job_text(job)
        if _has_any(text, filters.get("reject_terms", [])):
            continue
        if not _has_any(text, filters.get("required_terms", ["intern", "internship", "trainee"])):
            continue
        if filters.get("offline_only", True) and not is_offline_job(job, filters):
            continue

        profile, profile_score, profile_hits = choose_resume_profile(job, profiles)
        keywords = select_application_keywords(job, profile)
        score, reason = score_internship(job, config, profile_score, profile_hits, keywords)
        matches.append(
            InternshipMatch(
                job=job,
                score=score,
                reason=reason,
                resume_profile=profile,
                keywords=keywords,
            )
        )

    return sorted(matches, key=lambda item: item.score, reverse=True)


def choose_resume_profile(job, profiles: list[ResumeProfile]) -> tuple[ResumeProfile, int, list[str]]:
    text = _job_text(job)
    best = None
    for profile in profiles:
        hits = [term for term in profile.keywords if _term_in_text(term, text)]
        score = len(hits) * 8
        if any(term in _title(job) for term in profile.keywords):
            score += 8
        candidate = (score, profile, hits)
        if best is None or candidate[0] > best[0]:
            best = candidate

    assert best is not None
    return best[1], min(best[0], 45), best[2]


def select_application_keywords(job, profile: ResumeProfile, limit: int = 10) -> list[str]:
    text = _job_text(job)
    tags = [_norm(tag) for tag in getattr(job, "tags", []) or [] if _norm(tag)]
    selected: list[str] = []

    for tag in tags:
        if _term_in_text(tag, " ".join(profile.keywords)) or _term_in_text(tag, text):
            _append_unique(selected, tag)

    for term in profile.keywords:
        if _term_in_text(term, text):
            _append_unique(selected, term)

    for fallback in ("python", "javascript", "node.js", "fastapi", "react", "docker", "mongodb", "postgresql"):
        if _term_in_text(fallback, text):
            _append_unique(selected, fallback)

    return selected[:limit]


def score_internship(
    job,
    config: dict,
    profile_score: int,
    profile_hits: list[str],
    keywords: list[str],
) -> tuple[int, str]:
    filters = config.get("filters", {})
    text = _job_text(job)
    title = _title(job)
    score = 35 + profile_score
    reasons = ["offline internship"]

    if "internship" in title or "intern" in title:
        score += 10
        reasons.append("internship title")
    if any(term in title for term in ("backend", "software", "developer", "sde", "full stack", "fullstack", "ai")):
        score += 8
        reasons.append("target engineering title")
    if _location_matches(job, filters.get("preferred_locations", [])):
        score += 8
        reasons.append("preferred city")
    if _posted_recently(getattr(job, "posted_date", "")):
        score += 4
        reasons.append("fresh posting")
    if keywords:
        score += min(8, len(keywords))
        reasons.append("keywords: " + ", ".join(keywords[:5]))
    if profile_hits:
        reasons.append("resume: " + ", ".join(profile_hits[:5]))
    if any(term in text for term in ("sales", "marketing", "business development", "hr intern")):
        score -= 25
        reasons.append("non-engineering penalty")

    return max(0, min(100, score)), "; ".join(reasons)


def is_offline_job(job, filters: dict) -> bool:
    text = _job_text(job)
    reject_terms = [_norm(term) for term in filters.get("reject_terms", [])]
    if _has_any(text, reject_terms):
        return False

    location = _norm(getattr(job, "location", ""))
    if not location or location in {"n/a", "remote"}:
        return False

    preferred_locations = [_norm(term) for term in filters.get("preferred_locations", [])]
    if preferred_locations and not any(term in location for term in preferred_locations):
        return False

    return True


def write_internship_plan(matches: list[InternshipMatch], path: Path = INTERNSHIP_PLAN_FILE) -> None:
    fieldnames = [
        "job_id",
        "title",
        "company",
        "location",
        "experience",
        "posted_date",
        "score",
        "reason",
        "resume_profile",
        "resume_path",
        "application_keywords",
        "apply_link",
        "tags",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for match in matches:
            job = match.job
            writer.writerow(
                {
                    "job_id": job.job_id,
                    "title": job.title,
                    "company": job.company,
                    "location": job.location,
                    "experience": job.experience,
                    "posted_date": job.posted_date,
                    "score": match.score,
                    "reason": match.reason,
                    "resume_profile": match.resume_profile.label,
                    "resume_path": str(match.resume_profile.path),
                    "application_keywords": ", ".join(match.keywords),
                    "apply_link": job.apply_link,
                    "tags": ", ".join(job.tags or []),
                }
            )


def print_internship_matches(matches: list[InternshipMatch], limit: int = 25) -> None:
    print("\nOffline internship matches")
    print("-" * 120)
    for index, match in enumerate(matches[:limit], start=1):
        job = match.job
        print(
            f"{index:>2}. {match.score:>3}/100 | {job.title[:38]:<38} "
            f"| {job.company[:24]:<24} | {job.location[:20]:<20} | {match.resume_profile.id}"
        )
        print(f"    keywords: {', '.join(match.keywords[:8])}")
        print(f"    {match.reason[:180]}")


def load_internship_applied_ids(path: Path = INTERNSHIP_APPLIED_FILE) -> set[str]:
    # 1. Try pulling from SQL DB
    try:
        from src.careerflow.db import execute_query
        rows = execute_query("SELECT job_id FROM applied_jobs")
        db_ids = {row["job_id"] for row in rows if row.get("job_id")}
        if db_ids:
            return db_ids
    except Exception as e:
        print(f"[DATABASE WARNING] Failed to load applied job IDs from DB: {e}. Falling back to CSV.")

    # 2. Fallback to legacy CSV
    if not path.exists():
        return set()
    try:
        with path.open("r", newline="", encoding="utf-8") as f:
            return {row["job_id"] for row in csv.DictReader(f) if row.get("job_id")}
    except Exception:
        return set()


def save_internship_applied(match: InternshipMatch, path: Path = INTERNSHIP_APPLIED_FILE) -> None:
    # 1. Save to SQL DB
    try:
        from src.careerflow.db import save_applied_job_to_db, save_timeline_event
        save_applied_job_to_db(
            job_id=match.job.job_id,
            title=match.job.title,
            company=match.job.company,
            score=match.score,
            resume_profile=match.resume_profile.id
        )
        save_timeline_event(f"Applied successfully to {match.job.title} @ {match.job.company}", "success")
    except Exception as e:
        print(f"[DATABASE WARNING] Failed to save applied job to database: {e}")

    # 2. Save to legacy CSV backup
    try:
        file_exists = path.exists()
        with path.open("a", newline="", encoding="utf-8") as f:
            fieldnames = [
                "job_id",
                "title",
                "company",
                "score",
                "resume_profile",
                "keywords",
                "applied_at",
            ]
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            if not file_exists:
                writer.writeheader()
            writer.writerow(
                {
                    "job_id": match.job.job_id,
                    "title": match.job.title,
                    "company": match.job.company,
                    "score": match.score,
                    "resume_profile": match.resume_profile.id,
                    "keywords": ", ".join(match.keywords),
                    "applied_at": datetime.utcnow().isoformat(),
                }
            )
    except Exception as e:
        print(f"[CSV WARNING] Failed to write applied job backup to CSV: {e}")



def _job_text(job) -> str:
    parts = [
        getattr(job, "title", ""),
        getattr(job, "company", ""),
        getattr(job, "location", ""),
        getattr(job, "experience", ""),
        getattr(job, "salary", ""),
        getattr(job, "posted_date", ""),
        getattr(job, "description", ""),
        " ".join(getattr(job, "tags", []) or []),
        _flatten_metadata(getattr(job, "metadata", {}) or {}),
    ]
    return _norm(" ".join(str(part) for part in parts if part))


def _flatten_metadata(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(_flatten_metadata(v) for v in value.values())
    if isinstance(value, list):
        return " ".join(_flatten_metadata(v) for v in value)
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    return ""


def _title(job) -> str:
    return _norm(getattr(job, "title", ""))


def _location_matches(job, locations: Iterable[str]) -> bool:
    location = _norm(getattr(job, "location", ""))
    return any(_norm(term) in location for term in locations)


def _posted_recently(posted_date: str) -> bool:
    posted = _norm(posted_date)
    if any(term in posted for term in ("today", "hour", "just now", "yesterday")):
        return True
    match = re.search(r"(\d+)\s*day", posted)
    return bool(match and int(match.group(1)) <= 3)


def _has_any(text: str, terms: Iterable[str]) -> bool:
    return any(_term_in_text(_norm(term), text) for term in terms)


def _term_in_text(term: str, text: str) -> bool:
    if not term:
        return False
    if " " in term or "." in term or "/" in term:
        return term in text
    return bool(re.search(rf"\b{re.escape(term)}\b", text))


def _append_unique(values: list[str], value: str) -> None:
    value = _norm(value)
    if value and value not in values:
        values.append(value)


def _norm(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value).strip().lower())
