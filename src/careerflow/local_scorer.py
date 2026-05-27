from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable


@dataclass
class ScoreResult:
    score: int
    reason: str


def _normalise_terms(values: Iterable[str]) -> set[str]:
    return {str(v).strip().lower() for v in values if str(v).strip()}


def _parse_experience_range(experience: str) -> tuple[int, int]:
    numbers = [int(n) for n in re.findall(r"\d+", experience or "")]
    if len(numbers) >= 2:
        return numbers[0], numbers[1]
    if len(numbers) == 1:
        return numbers[0], numbers[0]
    return 0, 99


def _posted_recency_bonus(posted_date: str) -> int:
    posted = (posted_date or "").lower()
    if any(term in posted for term in ("today", "hour", "just now")):
        return 8
    if "yesterday" in posted:
        return 5
    match = re.search(r"(\d+)\s*day", posted)
    if match and int(match.group(1)) <= 2:
        return 3
    return 0


def score_job(job, config: dict) -> ScoreResult:
    candidate = config.get("candidate", {})
    primary = _normalise_terms(candidate.get("primary_skills", []))
    secondary = _normalise_terms(candidate.get("secondary_skills", []))
    preferred_keywords = _normalise_terms(candidate.get("preferred_keywords", []))
    target_roles = _normalise_terms(candidate.get("target_roles", []))
    avoid_titles = _normalise_terms(candidate.get("avoid_titles", []))
    avoid_companies = _normalise_terms(candidate.get("avoid_companies", []))
    preferred_locations = _normalise_terms(candidate.get("preferred_locations", []))

    title = (getattr(job, "title", "") or "").lower()
    company = (getattr(job, "company", "") or "").lower()
    location = (getattr(job, "location", "") or "").lower()
    tags = _normalise_terms(getattr(job, "tags", []) or [])
    description = (getattr(job, "description", "") or "").lower()
    haystack = " ".join([title, company, location, description, " ".join(tags)])

    if any(term in title for term in avoid_titles):
        return ScoreResult(0, "title veto")
    if any(term in company for term in avoid_companies):
        return ScoreResult(0, "company veto")

    score = 20
    reasons: list[str] = []

    primary_hits = sorted(term for term in primary if term in haystack or term in tags)
    secondary_hits = sorted(term for term in secondary if term in haystack or term in tags)
    if primary_hits:
        score += min(38, len(primary_hits) * 7)
        reasons.append("primary skill match: " + ", ".join(primary_hits[:4]))
    if secondary_hits:
        score += min(18, len(secondary_hits) * 4)
        reasons.append("secondary match: " + ", ".join(secondary_hits[:3]))

    if any(role in title for role in target_roles):
        score += 14
        reasons.append("target role title")
    elif any(keyword in title for keyword in ("backend", "sde", "software engineer", "developer")):
        score += 8
        reasons.append("software/backend title")

    preferred_hits = sorted(term for term in preferred_keywords if term in haystack)
    if preferred_hits:
        score += min(10, len(preferred_hits) * 3)
        reasons.append("preferred domain: " + ", ".join(preferred_hits[:3]))

    if any(loc and loc in location for loc in preferred_locations):
        score += 8
        reasons.append("preferred location")

    exp_min, exp_max = _parse_experience_range(getattr(job, "experience", "") or "")
    years = float(candidate.get("experience_years", 0))
    if exp_min <= years + 1 and exp_max >= max(0, years - 1):
        score += 8
        reasons.append("experience fit")
    elif exp_min > years + 2:
        score -= 18
        reasons.append("experience stretch")

    recency = _posted_recency_bonus(getattr(job, "posted_date", "") or "")
    if recency:
        score += recency
        reasons.append("fresh posting")

    if not primary_hits and not secondary_hits:
        score = min(score, 25)
        reasons.append("low stack overlap")

    score = max(0, min(100, score))
    return ScoreResult(score, "; ".join(reasons) or "basic match")
