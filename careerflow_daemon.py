#!/usr/bin/env python
"""
CareerFlow Autonomous Assistant Daemon

Features:
  - 100% Autonomous. Run it on a server and let it do all the work.
  - Automatically loads your credentials & OpenRouter key from .env.
  - Periodic Search Loop: Queries and scores new SDE/AI internships.
  - Dynamic ATS-optimized Resume Compiler: Generates a tailored SDE resume .docx on-the-fly,
    weaving in AI-tailored keyword bullets, and uploads it before each application.
  - Intelligent Questionnaire Answering: Completes multi-question recruiter forms on the fly.
  - Daily Profile Freshness Booster: Re-updates your headline and master resume once a day
    (around 9 AM - 10 AM IST) to guarantee your profile stays #1 in recruiter search views.
"""

import os
import sys
import time
import logging
from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv

# Ensure root path is imported
sys.path.append(str(Path(__file__).parent.absolute()))

from src.client.naukri_client import NaukriLoginClient
from src.client.job_client import NaukriJobClient
from src.careerflow.config import load_config
from src.careerflow.internships import (
    fetch_internship_jobs,
    match_internships,
    load_internship_applied_ids,
    save_internship_applied,
)
from src.careerflow.ai_engine import (
    generate_tailored_resume,
    generate_optimized_headline,
    answer_questionnaire,
    load_knowledge,
)
from src.careerflow.resume_docx_generator import build_tailored_resume_docx

# ---------------------------------------------------------------------------
# Logging Setup
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("careerflow_assistant.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("careerflow_assistant")

# ---------------------------------------------------------------------------
# Daemon Configuration
# ---------------------------------------------------------------------------
CHECK_INTERVAL_SECONDS = 3600 * 2 # Check for new jobs every 2 hours
PROFILE_REFRESH_INTERVAL_HOURS = 24

class AutonomousAssistant:
    def __init__(self):
        load_dotenv()
        self.username = os.getenv("USERNAME")
        self.password = os.getenv("PASSWORD")
        self.api_key = os.getenv("OPENROUTER_API_KEY")
        self.confirm_apply = os.getenv("CAREERFLOW_CONFIRM_APPLY", "false").lower() == "true"
        
        self.client = None
        self.job_client = None
        self.last_refresh_time = None
        try:
            from src.careerflow.db import get_statistic
            last_run = get_statistic("last_refresh_run", "Never")
            if last_run != "Never":
                self.last_refresh_time = datetime.strptime(last_run, "%Y-%m-%d %H:%M:%S")
                logger.info(f"Loaded last profile refresh time from DB: {self.last_refresh_time}")
        except Exception as e:
            logger.warning(f"Failed to load last refresh time from DB: {e}")
        
        # Verify credentials

        if not self.username or not self.password:
            logger.critical("Naukri USERNAME/PASSWORD credentials not configured in .env!")
            sys.exit(1)
        if not self.api_key or self.api_key == "your_openrouter_api_key":
            logger.critical("OPENROUTER_API_KEY not configured in .env! AI matching and resumes will be offline.")
            sys.exit(1)

    def authenticate(self):
        """Establish session with Naukri."""
        logger.info(f"Authenticating session for {self.username}...")
        try:
            self.client = NaukriLoginClient(self.username, self.password)
            self.client.login()
            self.job_client = NaukriJobClient(self.client)
            logger.info("Successfully established active Naukri session.")
            return True
        except Exception as e:
            logger.error(f"Failed to authenticate with Naukri: {e}")
            return False

    def check_and_boost_freshness(self):
        """Reset the Naukri 'last updated' timer once every 24 hours to keep the profile #1."""
        now = datetime.now()
        
        # Check if 24 hours have passed since last refresh
        if self.last_refresh_time and (now - self.last_refresh_time) < timedelta(hours=PROFILE_REFRESH_INTERVAL_HOURS):
            return
            
        logger.info("Triggering Daily Profile Freshness boost...")
        try:
            # 1. Ask OpenRouter to generate an SEO-optimized headline based on current profile skills
            logger.info("Generating SEO-optimized headline via OpenRouter...")
            optimized = generate_optimized_headline(
                target_role="Backend Developer & AI Automation Developer",
                current_headline="Backend Developer Intern | Python, Node.js, FastAPI, AI Automation | Bangalore"
            )
            headline = optimized.get("headline")
            
            if headline:
                logger.info(f"Submitting profile headline update: '{headline}'")
                self.client.update_profile(headline=headline)
            
            # 2. Upload master resume to trigger update timestamp
            master_resume = Path("resumes/backend_developer_intern.pdf")
            if master_resume.exists():
                logger.info(f"Re-uploading master resume to reset visibility clock...")
                res = self.client.update_resume(str(master_resume))
                logger.info(f"Master resume upload response status: {res.status_code}")
                
            self.last_refresh_time = now
            logger.info("✅ Profile successfully refreshed and bumped to top recruiter views!")
            try:
                from src.careerflow.db import increment_statistic, set_statistic, save_timeline_event
                increment_statistic("profile_refreshes_total")
                set_statistic("last_refresh_run", now.strftime("%Y-%m-%d %H:%M:%S"))
                save_timeline_event("Autonomous Profile Refresh & Resume Bump Completed", "success")
            except Exception as db_err:
                logger.error(f"Failed to update refresh stats in database: {db_err}")
        except Exception as e:
            logger.error(f"Failed to complete daily profile freshness boost: {e}")


    def run_application_loop(self):
        """Automatically find new postings, tailor resumes, and submit applications."""
        logger.info("Fetching and analyzing Bangalore SDE/AI internships...")
        
        try:
            config = load_config("config/internship_profile.json")
            application = config.get("application", {})
            min_score = int(config.get("scoring", {}).get("min_apply_score", 60))
            daily_limit = int(application.get("daily_limit", 25))
            delay_seconds = int(application.get("delay_seconds", 5))
            
            # Fetch Bangalore jobs
            jobs = fetch_internship_jobs(self.job_client, config)
            logger.info(f"Fetched {len(jobs)} total job listings.")
            
            # Run local and resume keyword scoring
            from src.careerflow.internships import match_internships
            matches = [m for m in match_internships(jobs, config) if m.score >= min_score]
            logger.info(f"Found {len(matches)} matched jobs above scoring threshold of {min_score}/100.")
            
            applied_ids = load_internship_applied_ids()
            applied_count = 0
            
            for match in matches:
                if applied_count >= daily_limit:
                    logger.info("Reached daily configured application limit.")
                    break
                    
                job = match.job
                if job.job_id in applied_ids:
                    continue
                    
                # Skip external links
                if application.get("skip_external_apply", True) and self.job_client.is_external_apply(job.job_id):
                    logger.info(f"[skip] Job {job.title} @ {job.company} redirects to external site.")
                    continue
                
                logger.info(f"🎯 AUTONOMOUS MATCH: {match.score}/100 | {job.title} @ {job.company}")
                
                # ---- STEP 1: AI CUSTOMIZED RESUME COMPILATION ----
                logger.info("Weaving job-specific keywords into customized resume bullet points...")
                tailored_data = generate_tailored_resume(
                    job_title=job.title,
                    company=job.company,
                    job_description=job.description
                )
                
                if "error" in tailored_data:
                    logger.error(f"Failed to generate tailored resume via OpenRouter: {tailored_data['error']}")
                    continue
                
                # Compile customized DOCX on the fly
                knowledge = load_knowledge()
                tailored_docx_path = f"resumes/tailored_{job.job_id}.docx"
                build_tailored_resume_docx(
                    candidate_knowledge=knowledge,
                    tailored_data=tailored_data,
                    output_path=tailored_docx_path
                )
                
                # Re-upload customized resume
                if Path(tailored_docx_path).exists():
                    logger.info(f"Uploading dynamic keyword-optimized SDE resume for '{job.company}'...")
                    upload_res = self.client.update_resume(tailored_docx_path)
                    logger.info(f"Tailored resume uploaded. Status: {upload_res.status_code}")
                    
                    # Clean up temporary tailored file to keep server clean
                    try:
                        os.remove(tailored_docx_path)
                    except Exception:
                        pass
                
                # ---- STEP 2: APPLY FOR THE JOB ----
                logger.info(f"Submitting application to {job.title}...")
                result = self.job_client.apply_job(
                    job,
                    mandatory_skills=match.keywords[:3],
                    optional_skills=match.keywords[3:10],
                    source="search",
                )
                
                job_result = (result.get("jobs") or [{}])[0]
                
                # ---- STEP 3: INTELLIGENT QUESTIONNAIRE ANSWERING ----
                if job_result.get("questionnaire"):
                    logger.info("Job requires questionnaire. Invoking OpenRouter AI questionnaire solver...")
                    answers = answer_questionnaire(
                        questions=job_result["questionnaire"],
                        job_title=job.title,
                        company=job.company
                    )
                    
                    logger.info(f"AI generated {len(answers)} answers successfully. Submitting to Naukri...")
                    sid = datetime.utcnow().strftime("%Y%m%d%H%M%S") + "0000000"
                    self.job_client.handle_static_questionnaire_and_apply(
                        job,
                        questionnaire=job_result["questionnaire"],
                        sid=sid,
                        mandatory_skills=match.keywords[:3],
                        optional_skills=match.keywords[3:10],
                        source="search",
                        answers=answers
                    )
                
                # Save application to prevent duplicates
                save_internship_applied(match)
                
                # Applied log compatibility
                from careerflow import save_applied
                save_applied(job, match.score)
                
                applied_ids.add(job.job_id)
                applied_count += 1
                logger.info(f"✅ Application successfully sent for {job.title} @ {job.company}!")
                
                # Sleep to match natural human speed and avoid IP throttling
                time.sleep(delay_seconds)
                
            logger.info(f"Application cycle completed. Submissions sent: {applied_count}")
        except Exception as e:
            logger.error(f"Error during application loop: {e}")

    def run_indefinitely(self):
        """Daemon entry loop."""
        logger.info("==================================================")
        logger.info("   CAREERFLOW AI AUTONOMOUS ASSISTANT ACTIVATED   ")
        logger.info("==================================================")
        logger.info(f"Daemon running. Interval: {CHECK_INTERVAL_SECONDS / 3600:.1f} hours.")
        logger.info(f"Confirm Apply: {self.confirm_apply}")
        logger.info("--------------------------------------------------")
        
        while True:
            try:
                # Always authenticate or refresh session on each cycle
                if not self.authenticate():
                    logger.error("Authentication failed. Will retry in 10 minutes...")
                    time.sleep(600)
                    continue
                
                # Step 1: Handle daily visibility bump
                self.check_and_boost_freshness()
                
                # Step 2: Fetch and auto-apply with dynamic AI resumes & questionnaire answers
                self.run_application_loop()
                
                # Disconnect to release session safely
                self.client = None
                self.job_client = None
                
                logger.info(f"All done for this cycle. Sleeping for {CHECK_INTERVAL_SECONDS / 3600:.1f} hours...")
                time.sleep(CHECK_INTERVAL_SECONDS)
                
            except KeyboardInterrupt:
                logger.info("Daemon interrupted by keyboard. Exiting...")
                break
            except Exception as e:
                logger.critical(f"Unhandled daemon error: {e}. Retrying in 1 hour...")
                time.sleep(3600)

if __name__ == "__main__":
    # Write PID to file for server.py monitoring status
    try:
        with open("careerflow_daemon.pid", "w") as f:
            f.write(str(os.getpid()))
    except Exception:
        pass

    assistant = AutonomousAssistant()
    assistant.run_indefinitely()
