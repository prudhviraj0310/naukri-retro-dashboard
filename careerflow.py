from __future__ import annotations

import argparse
import csv
import os
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from src.careerflow.config import DEFAULT_CONFIG_PATH, load_config, resolve_workspace_path
from src.careerflow.internships import (
    INTERNSHIP_APPLIED_FILE,
    INTERNSHIP_PLAN_FILE,
    fetch_internship_jobs,
    load_internship_applied_ids,
    match_internships,
    print_internship_matches,
    save_internship_applied,
    write_internship_plan,
)
from src.careerflow.local_scorer import score_job
from src.client.job_client import NaukriJobClient
from src.client.jop_classifier import JobFilterPipeline2
from src.client.naukri_client import NaukriLoginClient


PLAN_FILE = Path("careerflow_plan.csv")
APPLIED_FILE = Path("applied_jobs.csv")
DEFAULT_INTERNSHIP_CONFIG_PATH = Path("config/internship_profile.json")


def _openai_key() -> str | None:
    return os.getenv("OPENAI_API_KEY") or os.getenv("OPEN_API_KEY")


def _credentials(username: str | None = None, password: str | None = None) -> tuple[str, str]:
    username = username or os.getenv("USERNAME")
    password = password or os.getenv("PASSWORD")
    if not username or not password:
        raise RuntimeError("Set USERNAME and PASSWORD in .env before running Naukri actions.")
    return username, password


def login_client(
    username: str | None = None,
    password: str | None = None,
    otp: str | None = None,
    is_mobile: bool = True,
) -> NaukriLoginClient:
    otp = otp or os.getenv("NAUKRI_OTP")
    if otp:
        target = username or os.getenv("NAUKRI_MOBILE") or os.getenv("USERNAME")
        if not target:
            raise RuntimeError("Set NAUKRI_MOBILE or pass --mobile when using OTP login.")
        client = NaukriLoginClient(target, "")
        client.verify_otp(otp=otp, username=target, is_mobile=is_mobile)
        return client

    username, password = _credentials(username=username, password=password)
    client = NaukriLoginClient(username, password)
    client.login()
    return client


def _login_mobile(args, config: dict | None = None) -> str | None:
    return (
        getattr(args, "mobile", None)
        or (config or {}).get("account", {}).get("mobile")
        or os.getenv("NAUKRI_MOBILE")
        or os.getenv("USERNAME")
    )


def fetch_jobs(job_client: NaukriJobClient, config: dict) -> list:
    search = config.get("search", {})
    queries = search.get("queries", [])
    experience_levels = search.get("experience_levels", [2])
    pages = int(search.get("pages", 1))
    job_age = int(search.get("job_age_days", 2))
    results_per_page = int(search.get("results_per_page", 20))

    seen_ids: set[str] = set()
    jobs = []

    for query in queries:
        keyword = query["keyword"]
        location = query.get("location", "")
        for experience in experience_levels:
            for page in range(1, pages + 1):
                result = job_client.search_jobs(
                    keyword=keyword,
                    location=location,
                    experience=experience,
                    job_age=job_age,
                    page=page,
                    results_per_page=results_per_page,
                )
                new_jobs = [job for job in result if job.job_id and job.job_id not in seen_ids]
                for job in new_jobs:
                    seen_ids.add(job.job_id)
                jobs.extend(new_jobs)
                print(
                    f"[fetch] {keyword} | {location or 'All India'} | exp={experience} "
                    f"| page={page}: {len(result)} fetched, {len(new_jobs)} new"
                )
                time.sleep(1.2)

    return jobs


def score_jobs(jobs: list, config: dict, use_ai: bool = True) -> list[dict]:
    scoring = config.get("scoring", {})
    max_jobs = int(scoring.get("max_jobs_to_score", 120))
    jobs = jobs[:max_jobs]

    key = _openai_key()
    if use_ai and scoring.get("use_ai_scoring", True) and key:
        pipeline = JobFilterPipeline2(
            openai_api_key=key,
            min_apply_score=int(scoring.get("min_apply_score", 72)),
            daily_apply_limit=int(config.get("application", {}).get("daily_limit", 12)),
        )
        ranked = pipeline.run(jobs)
        return [
            {
                "job": next((job for job in jobs if job.job_id == item.get("job_id")), None),
                "score": int(item.get("ai_score", item.get("score", 0)) or 0),
                "reason": item.get("ai_reason") or item.get("reason") or "",
                "source": "ai",
            }
            for item in ranked
        ]

    ranked = []
    for job in jobs:
        result = score_job(job, config)
        ranked.append(
            {
                "job": job,
                "score": result.score,
                "reason": result.reason,
                "source": "local",
            }
        )
    return sorted(ranked, key=lambda item: item["score"], reverse=True)


def write_plan(scored_jobs: list[dict], path: Path = PLAN_FILE) -> None:
    fieldnames = [
        "job_id",
        "title",
        "company",
        "location",
        "experience",
        "posted_date",
        "score",
        "reason",
        "source",
        "apply_link",
        "tags",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for item in scored_jobs:
            job = item["job"]
            if not job:
                continue
            writer.writerow(
                {
                    "job_id": job.job_id,
                    "title": job.title,
                    "company": job.company,
                    "location": job.location,
                    "experience": job.experience,
                    "posted_date": job.posted_date,
                    "score": item["score"],
                    "reason": item["reason"],
                    "source": item["source"],
                    "apply_link": job.apply_link,
                    "tags": ", ".join(job.tags or []),
                }
            )


def print_ranked(scored_jobs: list[dict], limit: int = 20) -> None:
    print("\nTop matches")
    print("-" * 100)
    for index, item in enumerate(scored_jobs[:limit], start=1):
        job = item["job"]
        if not job:
            continue
        print(
            f"{index:>2}. {item['score']:>3}/100 | {job.title[:42]:<42} "
            f"| {job.company[:24]:<24} | {job.location[:18]:<18}"
        )
        print(f"    {item['reason'][:150]}")


def load_applied_ids() -> set[str]:
    if not APPLIED_FILE.exists():
        return set()
    with APPLIED_FILE.open("r", newline="", encoding="utf-8") as f:
        return {row["job_id"] for row in csv.DictReader(f) if row.get("job_id")}


def save_applied(job, score: int) -> None:
    file_exists = APPLIED_FILE.exists()
    with APPLIED_FILE.open("a", newline="", encoding="utf-8") as f:
        fieldnames = ["job_id", "title", "company", "score", "applied_at"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerow(
            {
                "job_id": job.job_id,
                "title": job.title,
                "company": job.company,
                "score": score,
                "applied_at": datetime.utcnow().isoformat(),
            }
        )


def command_plan(args) -> None:
    config = load_config(args.config)
    client = login_client(username=_login_mobile(args, config), otp=args.otp)
    job_client = NaukriJobClient(client)
    jobs = fetch_jobs(job_client, config)
    scored = score_jobs(jobs, config, use_ai=not args.local_score)
    write_plan(scored)
    print_ranked(scored, limit=args.limit)
    print(f"\nSaved plan to {PLAN_FILE}")


def command_apply(args) -> None:
    config = load_config(args.config)
    min_score = int(config.get("scoring", {}).get("min_apply_score", 72))
    daily_limit = int(config.get("application", {}).get("daily_limit", 12))
    delay_seconds = int(config.get("application", {}).get("delay_seconds", 4))
    answer_questionnaires = bool(config.get("application", {}).get("answer_questionnaires", False))
    confirm = args.confirm_apply or os.getenv("CAREERFLOW_CONFIRM_APPLY", "").lower() == "true"

    client = login_client(username=_login_mobile(args, config), otp=args.otp)
    job_client = NaukriJobClient(client)
    jobs = fetch_jobs(job_client, config)
    scored = score_jobs(jobs, config, use_ai=not args.local_score)
    candidates = [item for item in scored if item["job"] and item["score"] >= min_score]

    applied_ids = load_applied_ids()
    applied_count = 0
    print(f"\nApply mode: {'LIVE' if confirm else 'DRY RUN'}")

    for item in candidates:
        if applied_count >= daily_limit:
            break

        job = item["job"]
        if job.job_id in applied_ids:
            print(f"[skip] already applied: {job.title} @ {job.company}")
            continue

        if config.get("application", {}).get("skip_external_apply", True) and job_client.is_external_apply(job.job_id):
            print(f"[skip] external apply: {job.title} @ {job.company}")
            continue

        print(f"[match] {item['score']}/100 {job.title} @ {job.company}")
        if not confirm:
            print("       dry-run only; pass --confirm-apply to submit")
            continue

        result = job_client.apply_job(
            job,
            mandatory_skills=(job.tags or [])[:2],
            optional_skills=(job.tags or [])[2:],
            source="search",
        )
        job_result = (result.get("jobs") or [{}])[0]
        if job_result.get("questionnaire") and not answer_questionnaires:
            print("       questionnaire detected; skipped by config")
            continue

        if job_result.get("questionnaire"):
            sid = datetime.utcnow().strftime("%Y%m%d%H%M%S") + "0000000"
            job_client.handle_static_questionnaire_and_apply(
                job,
                questionnaire=job_result["questionnaire"],
                sid=sid,
                mandatory_skills=(job.tags or [])[:2],
                optional_skills=(job.tags or [])[2:],
                source="search",
            )

        save_applied(job, item["score"])
        applied_ids.add(job.job_id)
        applied_count += 1
        time.sleep(delay_seconds)

    write_plan(scored)
    print(f"\nApplied: {applied_count}. Plan saved to {PLAN_FILE}")


def command_refresh_profile(args) -> None:
    config = load_config(args.config)
    refresh = config.get("profile_refresh", {})
    resume_path = resolve_workspace_path(refresh.get("resume_path"))
    confirm = args.confirm_profile_update

    print(f"Profile refresh mode: {'LIVE' if confirm else 'DRY RUN'}")
    print(f"Headline: {refresh.get('headline')}")
    print(f"Summary: {refresh.get('summary')}")
    print(f"Resume: {resume_path}")

    if not confirm:
        print("No changes submitted. Pass --confirm-profile-update to update Naukri.")
        return

    client = login_client(username=_login_mobile(args, config), otp=args.otp)
    if refresh.get("headline") or refresh.get("summary"):
        result = client.update_profile(
            headline=refresh.get("headline"),
            summary=refresh.get("summary"),
        )
        print(f"Profile update status: {result.status_code}")

    if resume_path and resume_path.exists():
        result = client.update_resume(str(resume_path))
        print(f"Resume update status: {result.status_code}")
    elif resume_path:
        print(f"Resume path does not exist, skipped: {resume_path}")


def command_send_otp(args) -> None:
    config = {}
    if args.internship_config and Path(args.internship_config).exists():
        config = load_config(args.internship_config)
    mobile = args.mobile or config.get("account", {}).get("mobile") or os.getenv("NAUKRI_MOBILE")
    if not mobile:
        raise RuntimeError("Pass --mobile or set NAUKRI_MOBILE.")

    client = NaukriLoginClient(mobile, "")
    response = client.send_otp(username=mobile, is_mobile=True)
    print("OTP requested")
    if isinstance(response, dict) and response.get("message"):
        print(response["message"])


def command_internship_plan(args) -> None:
    config = load_config(args.internship_config)
    if args.otp or os.getenv("PASSWORD"):
        client = login_client(username=_login_mobile(args, config), otp=args.otp)
    else:
        client = NaukriLoginClient("", "")
    job_client = NaukriJobClient(client)
    jobs = fetch_internship_jobs(job_client, config)
    matches = match_internships(jobs, config)
    write_internship_plan(matches)
    print_internship_matches(matches, limit=args.limit)
    print(f"\nSaved internship plan to {INTERNSHIP_PLAN_FILE}")


def command_internship_apply(args) -> None:
    config = load_config(args.internship_config)
    application = config.get("application", {})
    min_score = int(config.get("scoring", {}).get("min_apply_score", 60))
    daily_limit = args.max_applications or int(application.get("daily_limit", 25))
    delay_seconds = int(application.get("delay_seconds", 5))
    answer_questionnaires = bool(application.get("answer_questionnaires", False))
    upload_matched_resume = bool(application.get("upload_matched_resume", True))
    confirm = args.confirm_apply or os.getenv("CAREERFLOW_CONFIRM_APPLY", "").lower() == "true"

    client = login_client(username=_login_mobile(args, config), otp=args.otp)
    job_client = NaukriJobClient(client)
    jobs = fetch_internship_jobs(job_client, config)
    matches = [match for match in match_internships(jobs, config) if match.score >= min_score]
    write_internship_plan(matches)

    applied_ids = load_internship_applied_ids() | load_applied_ids()
    applied_count = 0
    current_resume_path = None

    print(f"\nInternship apply mode: {'LIVE' if confirm else 'DRY RUN'}")
    for match in matches:
        if applied_count >= daily_limit:
            break

        job = match.job
        if job.job_id in applied_ids:
            print(f"[skip] already applied: {job.title} @ {job.company}")
            continue

        if application.get("skip_external_apply", True) and job_client.is_external_apply(job.job_id):
            print(f"[skip] external apply: {job.title} @ {job.company}")
            continue

        print(
            f"[internship-match] {match.score}/100 {job.title} @ {job.company} "
            f"| resume={match.resume_profile.id}"
        )
        print(f"                   keywords={', '.join(match.keywords[:8])}")
        if not confirm:
            print("                   dry-run only; pass --confirm-apply to submit")
            continue

        if upload_matched_resume:
            resume_path = match.resume_profile.path
            if not resume_path.exists():
                print(f"[skip] missing resume: {resume_path}")
                continue
            if current_resume_path != resume_path:
                result = client.update_resume(str(resume_path))
                print(f"[resume] uploaded {match.resume_profile.label}: {result.status_code}")
                current_resume_path = resume_path

        result = job_client.apply_job(
            job,
            mandatory_skills=match.keywords[:3],
            optional_skills=match.keywords[3:10],
            source="search",
        )
        job_result = (result.get("jobs") or [{}])[0]
        if job_result.get("questionnaire") and not answer_questionnaires:
            print("[skip] questionnaire detected; skipped by config")
            continue

        if job_result.get("questionnaire"):
            sid = datetime.utcnow().strftime("%Y%m%d%H%M%S") + "0000000"
            job_client.handle_static_questionnaire_and_apply(
                job,
                questionnaire=job_result["questionnaire"],
                sid=sid,
                mandatory_skills=match.keywords[:3],
                optional_skills=match.keywords[3:10],
                source="search",
            )

        save_internship_applied(match)
        save_applied(job, match.score)
        applied_ids.add(job.job_id)
        applied_count += 1
        time.sleep(delay_seconds)

    print(f"\nInternship applications submitted: {applied_count}")
    print(f"Plan saved to {INTERNSHIP_PLAN_FILE}")
    print(f"Application log: {INTERNSHIP_APPLIED_FILE}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="CareerFlow AI Naukri automation runner")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to candidate profile config")

    subparsers = parser.add_subparsers(dest="command", required=True)

    send_otp = subparsers.add_parser("send-otp", help="Send an OTP for Naukri mobile login")
    send_otp.add_argument("--mobile", help="Registered Naukri mobile number")
    send_otp.add_argument(
        "--internship-config",
        default=str(DEFAULT_INTERNSHIP_CONFIG_PATH),
        help="Path to internship config for account defaults",
    )
    send_otp.set_defaults(func=command_send_otp)

    plan = subparsers.add_parser("plan", help="Fetch and rank jobs, then write careerflow_plan.csv")
    plan.add_argument("--mobile", help="Registered Naukri mobile number for OTP login")
    plan.add_argument("--otp", help="Naukri OTP for mobile login")
    plan.add_argument("--local-score", action="store_true", help="Disable OpenAI scoring and use local scoring")
    plan.add_argument("--limit", type=int, default=20, help="Number of ranked jobs to print")
    plan.set_defaults(func=command_plan)

    apply = subparsers.add_parser("apply", help="Apply to ranked jobs; dry-run unless confirmed")
    apply.add_argument("--mobile", help="Registered Naukri mobile number for OTP login")
    apply.add_argument("--otp", help="Naukri OTP for mobile login")
    apply.add_argument("--local-score", action="store_true", help="Disable OpenAI scoring and use local scoring")
    apply.add_argument("--confirm-apply", action="store_true", help="Submit real Naukri applications")
    apply.set_defaults(func=command_apply)

    refresh = subparsers.add_parser("refresh-profile", help="Update Naukri headline, summary, and resume")
    refresh.add_argument("--mobile", help="Registered Naukri mobile number for OTP login")
    refresh.add_argument("--otp", help="Naukri OTP for mobile login")
    refresh.add_argument("--confirm-profile-update", action="store_true", help="Submit real profile changes")
    refresh.set_defaults(func=command_refresh_profile)

    internship_plan = subparsers.add_parser(
        "internship-plan",
        help="Fetch offline internships, select resume profiles, and write internship_plan.csv",
    )
    internship_plan.add_argument(
        "--internship-config",
        default=str(DEFAULT_INTERNSHIP_CONFIG_PATH),
        help="Path to internship config",
    )
    internship_plan.add_argument("--mobile", help="Registered Naukri mobile number for OTP login")
    internship_plan.add_argument("--otp", help="Naukri OTP for mobile login")
    internship_plan.add_argument("--limit", type=int, default=25, help="Number of matches to print")
    internship_plan.set_defaults(func=command_internship_plan)

    internship_apply = subparsers.add_parser(
        "internship-apply",
        help="Apply to offline internships; dry-run unless confirmed",
    )
    internship_apply.add_argument(
        "--internship-config",
        default=str(DEFAULT_INTERNSHIP_CONFIG_PATH),
        help="Path to internship config",
    )
    internship_apply.add_argument("--mobile", help="Registered Naukri mobile number for OTP login")
    internship_apply.add_argument("--otp", help="Naukri OTP for mobile login")
    internship_apply.add_argument("--confirm-apply", action="store_true", help="Submit real applications")
    internship_apply.add_argument("--max-applications", type=int, help="Override daily application limit")
    internship_apply.set_defaults(func=command_internship_apply)

    return parser


def main() -> None:
    load_dotenv()
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
