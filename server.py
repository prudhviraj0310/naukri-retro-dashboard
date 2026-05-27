import sys
import os
import threading
import time
from pathlib import Path
from datetime import datetime
import csv
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, HTTPException, BackgroundTasks, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import uvicorn

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

# Add repository root to path
sys.path.append(str(Path(__file__).parent.absolute()))

from src.client.naukri_client import NaukriLoginClient
from src.careerflow.config import load_config
from src.careerflow.ai_engine import (
    generate_tailored_resume,
    generate_optimized_headline,
    answer_questionnaire,
    get_ai_status,
    reset_client as reset_ai_client,
    reload_knowledge,
)

def keep_alive_ping():
    # Check multiple environment variable options for the app's external URL
    external_url = (
        os.environ.get("RENDER_EXTERNAL_URL") or 
        os.environ.get("RENDER_APP_URL") or 
        os.environ.get("APP_URL")
    )
    if not external_url:
        print("[KEEP-ALIVE] RENDER_EXTERNAL_URL, RENDER_APP_URL, and APP_URL are not set. Skipping self-ping background thread.")
        return
    
    # Normalize URL (ensure it has a scheme and starts with http)
    if not external_url.startswith("http"):
        external_url = "https://" + external_url
    
    ping_url = f"{external_url.rstrip('/')}/api/status"
    print(f"[KEEP-ALIVE] Spawning keep-alive ping thread targeting: {ping_url}...")
    import urllib.request
    
    # Wait a bit on boot to let the server start up
    time.sleep(15)
    
    while True:
        try:
            print(f"[KEEP-ALIVE] Pinging self at {ping_url}...")
            req = urllib.request.Request(
                ping_url, 
                headers={'User-Agent': 'CareerFlow-KeepAlive'}
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                response.read()
            print("[KEEP-ALIVE] Ping successful!")
        except Exception as e:
            print(f"[KEEP-ALIVE WARNING] Keep-alive ping failed: {e}")
        
        # Sleep for 4 minutes (240 seconds)
        time.sleep(240)

app = FastAPI(title="CareerFlow AI Dashboard", description="Sleek personal Naukri job search automation dashboard")


# Global Log Buffer & Redirector
global_log_buffer = []

class LogStreamRedirector:
    def __init__(self, original_stream, buffer):
        self.original_stream = original_stream
        self.buffer = buffer

    def write(self, data):
        self.original_stream.write(data)
        if data:
            self.buffer.append(data)

    def flush(self):
        self.original_stream.flush()

    def __getattr__(self, name):
        return getattr(self.original_stream, name)

# Redirect stdout to capture all prints
sys.stdout = LogStreamRedirector(sys.stdout, global_log_buffer)

# Global State Store
class ServerState:
    client: Optional[NaukriLoginClient] = None
    running_task: Optional[threading.Thread] = None
    running_task_name: Optional[str] = None
    last_profile_refresh_time: Optional[str] = None
    mobile_number: str = "8019642185" # Default from internship config

state = ServerState()

# Load mobile default from internship_profile.json
try:
    internship_config = load_config("config/internship_profile.json")
    state.mobile_number = internship_config.get("account", {}).get("mobile", state.mobile_number)
except Exception:
    pass

# Helper to run a function in a background thread
def run_task_in_background(task_name: str, func, *args, **kwargs):
    if state.running_task and state.running_task.is_alive():
        print(f"[WARNING] Task {state.running_task_name} is already running.")
        return False
    
    global_log_buffer.clear()
    print(f"[START] Triggered background execution for '{task_name}' at {datetime.now().strftime('%H:%M:%S')}")
    
    def wrapper():
        try:
            func(*args, **kwargs)
            print(f"[SUCCESS] Background task '{task_name}' completed successfully.")
        except Exception as e:
            print(f"[ERROR] Task '{task_name}' failed with error: {e}")
        finally:
            state.running_task = None
            state.running_task_name = None

    state.running_task_name = task_name
    state.running_task = threading.Thread(target=wrapper, daemon=True)
    state.running_task.start()
    return True

# Programmatic Flow Functions
def run_internship_plan_flow(client):
    from src.careerflow.internships import fetch_internship_jobs, match_internships, write_internship_plan, print_internship_matches
    from src.client.job_client import NaukriJobClient
    
    config = load_config("config/internship_profile.json")
    job_client = NaukriJobClient(client)
    
    print("[PLAN] Starting Bangalore Internship plan fetch...")
    jobs = fetch_internship_jobs(job_client, config)
    print(f"[PLAN] Fetched {len(jobs)} internship listings. Scoring and matching with resumes...")
    
    matches = match_internships(jobs, config)
    write_internship_plan(matches)
    
    print_internship_matches(matches, limit=25)
    print("[PLAN] ✅ Internship matching plan successfully saved to 'internship_plan.csv'.")
    try:
        from src.careerflow.db import set_statistic, save_timeline_event
        set_statistic("plan_total", str(len(matches)))
        save_timeline_event(f"Bangalore Internship matching sweep complete: {len(matches)} listings scored", "success")
    except Exception as db_err:
        print(f"[DATABASE ERROR] Failed to record sweep plan_total: {db_err}")


def run_internship_apply_flow(client, confirm_apply: bool):
    from src.careerflow.internships import (
        fetch_internship_jobs,
        match_internships,
        write_internship_plan,
        load_internship_applied_ids,
        save_internship_applied
    )
    from src.client.job_client import NaukriJobClient
    
    config = load_config("config/internship_profile.json")
    application = config.get("application", {})
    min_score = int(config.get("scoring", {}).get("min_apply_score", 60))
    daily_limit = int(application.get("daily_limit", 25))
    delay_seconds = int(application.get("delay_seconds", 5))
    answer_questionnaires = bool(application.get("answer_questionnaires", False))
    upload_matched_resume = bool(application.get("upload_matched_resume", True))
    
    job_client = NaukriJobClient(client)
    
    print("[APPLY] Fetching and matching Bangalore Internships...")
    jobs = fetch_internship_jobs(job_client, config)
    matches = [match for match in match_internships(jobs, config) if match.score >= min_score]
    write_internship_plan(matches)
    
    applied_ids = load_internship_applied_ids()
    applied_count = 0
    current_resume_path = None
    
    print(f"[APPLY] Mode: {'LIVE SUBMISSION' if confirm_apply else 'DRY RUN PREVIEW'}")
    
    for match in matches:
        if applied_count >= daily_limit:
            print("[APPLY] Reached daily limits configured in internship_profile.json.")
            break
            
        job = match.job
        if job.job_id in applied_ids:
            print(f"[skip] Already applied: {job.title} @ {job.company}")
            continue
            
        if application.get("skip_external_apply", True) and job_client.is_external_apply(job.job_id):
            print(f"[skip] Redirects to external company site: {job.title} @ {job.company}")
            continue
            
        print(f"[match] {match.score}/100 | {job.title} @ {job.company}")
        print(f"        Recommended Resume: {match.resume_profile.label} ({match.resume_profile.id})")
        print(f"        Matched Keywords: {', '.join(match.keywords[:6])}")
        
        if not confirm_apply:
            print("        (Dry-run only: select Live mode on dashboard to apply)")
            continue
            
        if upload_matched_resume:
            resume_path = match.resume_profile.path
            if not resume_path.exists():
                print(f"[warning] Resume file missing, skipping: {resume_path}")
                continue
            if current_resume_path != resume_path:
                print(f"[resume] Resume profile changed to '{match.resume_profile.label}'. Re-uploading...")
                result = client.update_resume(str(resume_path))
                print(f"[resume] Upload status: {result.status_code}")
                current_resume_path = resume_path
                
        print(f"[apply] Sending application to {job.title}...")
        result = job_client.apply_job(
            job,
            mandatory_skills=match.keywords[:3],
            optional_skills=match.keywords[3:10],
            source="search",
        )
        job_result = (result.get("jobs") or [{}])[0]
        if job_result.get("questionnaire") and not answer_questionnaires:
            print("        [skip] Questionnaire required; skipped by configuration.")
            continue
            
        if job_result.get("questionnaire"):
            sid = datetime.utcnow().strftime("%Y%m%d%H%M%S") + "0000000"
            api_key = os.environ.get("OPENROUTER_API_KEY", "")
            answers = None
            if api_key and api_key != "your_openrouter_api_key":
                print("        Handling questionnaire answers using OpenRouter AI...")
                try:
                    answers = answer_questionnaire(
                        questions=job_result["questionnaire"],
                        job_title=job.title,
                        company=job.company,
                    )
                    print(f"        [AI] Generated {len(answers)} answers successfully.")
                except Exception as e:
                    print(f"        [AI Error] Failed to generate answers: {e}. Falling back to static answers...")
            
            if not answers:
                print("        Handling static questionnaire answers...")
                
            job_client.handle_static_questionnaire_and_apply(
                job,
                questionnaire=job_result["questionnaire"],
                sid=sid,
                mandatory_skills=match.keywords[:3],
                optional_skills=match.keywords[3:10],
                source="search",
                answers=answers,
            )
            
        save_internship_applied(match)
        
        # General applied log compatibility
        from careerflow import save_applied
        save_applied(job, match.score)
        
        applied_ids.add(job.job_id)
        applied_count += 1
        print(f"[apply] ✅ Application successfully sent for {job.title} @ {job.company}!")
        time.sleep(delay_seconds)
        
    print(f"[APPLY] Finished. Total applications submitted: {applied_count}")

def run_profile_refresh_flow(client, confirm: bool):
    from src.careerflow.config import load_config, resolve_workspace_path
    
    config = load_config("config/candidate_profile.json")
    refresh = config.get("profile_refresh", {})
    resume_path = resolve_workspace_path(refresh.get("resume_path"))
    
    print(f"[REFRESH] Starting Profile Refresh...")
    print(f"[REFRESH] Configured Headline: {refresh.get('headline')}")
    print(f"[REFRESH] Configured Summary: {refresh.get('summary')}")
    print(f"[REFRESH] Configured Resume: {resume_path}")
    
    if not confirm:
        print("[REFRESH] (Dry-run preview: select LIVE mode to submit profile refresh to Naukri)")
        return
        
    if refresh.get("headline") or refresh.get("summary"):
        print("[REFRESH] Submitting headline and summary updates to Naukri profile...")
        result = client.update_profile(
            headline=refresh.get("headline"),
            summary=refresh.get("summary"),
        )
        print(f"[REFRESH] Profile update response status: {result.status_code}")
        
    if resume_path and resume_path.exists():
        print(f"[REFRESH] Uploading fresh resume file to Naukri...")
        result = client.update_resume(str(resume_path))
        print(f"[REFRESH] Resume upload response status: {result.status_code}")
        
    state.last_profile_refresh_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print("[REFRESH] ✅ Profile updated and resume successfully re-uploaded to keep visibility active!")
    try:
        from src.careerflow.db import increment_statistic, set_statistic, save_timeline_event
        increment_statistic("profile_refreshes_total")
        set_statistic("last_refresh_run", state.last_profile_refresh_time)
        save_timeline_event("Manual Profile Refresh & Resume Bump Completed", "success")
    except Exception as db_err:
        print(f"[DATABASE ERROR] Failed to record manual refresh to DB: {db_err}")


# Models for Request Bodies
class SendOtpRequest(BaseModel):
    mobile: str

class VerifyOtpRequest(BaseModel):
    mobile: str
    otp: str

class PasswordLoginRequest(BaseModel):
    username: str
    password: str

class RunActionRequest(BaseModel):
    action: str  # "plan", "apply", "refresh"
    confirm: bool = False

class AIGenerateResumeRequest(BaseModel):
    job_title: str
    company: str = ""
    job_description: str
    model: str = ""

class AIHeadlineRequest(BaseModel):
    target_role: str = ""
    current_headline: str = ""
    model: str = ""

class AISettingsRequest(BaseModel):
    api_key: str = ""
    model: str = ""

# API Routes
@app.get("/api/status")
def get_status():
    # Check if daemon is active in the background
    daemon_active = False
    pid_path = Path("careerflow_daemon.pid")
    if pid_path.exists():
        try:
            with open(pid_path, "r") as f:
                pid = int(f.read().strip())
            os.kill(pid, 0)
            daemon_active = True
        except Exception:
            pass

    running_name = state.running_task_name
    if not running_name and daemon_active:
        running_name = "Autonomous Daemon (Active)"

    if not state.client or not state.client.naukri_session:
        return {
            "authenticated": False,
            "mobile": state.mobile_number,
            "running_task": running_name,
            "profile": None
        }
    
    # Try fetching real-time dashboard data
    try:
        res = state.client._fetch_dashboard()
        dashboard_data = res.json()
        db = dashboard_data.get("dashBoard", {}) or dashboard_data
        profile_completeness = db.get("profileCompleteness", 85)
        last_updated = db.get("lastUpdated") or db.get("modifiedDate") or "Active Today"
        headline = db.get("resumeHeadline") or db.get("headline") or "Backend Engineer | Python, Node.js, AI"
        name = db.get("name") or db.get("candidateName") or "Prudhvi Raj"
    except Exception:
        profile_completeness = 85
        last_updated = state.last_profile_refresh_time or "Active Today"
        headline = "Backend Engineer | Python, Node.js, AI Automation"
        name = "Prudhvi Raj"

    # Fetch last_refresh_run from persistent statistics database
    try:
        from src.careerflow.db import get_statistic
        db_last_refresh = get_statistic("last_refresh_run", "Not run this session")
    except Exception:
        db_last_refresh = state.last_profile_refresh_time or "Not run this session"

    return {
        "authenticated": True,
        "mobile": state.mobile_number,
        "running_task": running_name,
        "profile": {
            "name": name,
            "headline": headline,
            "completeness": profile_completeness,
            "last_updated": last_updated,
            "last_refresh_run": db_last_refresh
        }
    }


@app.post("/api/send-otp")
def send_otp(req: SendOtpRequest):
    state.mobile_number = req.mobile
    state.client = NaukriLoginClient(req.mobile, "")
    try:
        res = state.client.send_otp(username=req.mobile, is_mobile=True)
        message = res.get("message") or "OTP successfully sent to your mobile number!"
        return {"success": True, "message": message}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/api/verify-otp")
def verify_otp(req: VerifyOtpRequest):
    if not state.client:
        state.client = NaukriLoginClient(req.mobile, "")
    try:
        state.client.verify_otp(otp=req.otp, username=req.mobile, is_mobile=True)
        return {"success": True, "message": "Authenticated successfully! Naukri session created."}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/api/login-password")
def login_password(req: PasswordLoginRequest):
    try:
        client = NaukriLoginClient(req.username, req.password)
        client.login()
        state.client = client
        state.mobile_number = req.username
        return {"success": True, "message": "Authenticated successfully with password!"}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.get("/api/stats")
def get_stats():
    from src.careerflow.db import execute_query, get_statistic, get_timeline_events
    
    # 1. Total applied from DB
    try:
        res = execute_query("SELECT COUNT(*) as c FROM applied_jobs")
        applied_count = res[0]["c"] if res else 0
    except Exception:
        applied_count = 0
        
    # 2. Applied today from DB
    try:
        today_str = datetime.utcnow().date().isoformat()
        res = execute_query("SELECT COUNT(*) as c FROM applied_jobs WHERE applied_at LIKE ?", (f"{today_str}%",))
        applied_today_count = res[0]["c"] if res else 0
    except Exception:
        applied_today_count = 0
        
    # 3. Plan total from statistics DB (falling back to parsing CSV)
    plan_count = int(get_statistic("plan_total", "0"))
    if plan_count == 0:
        plan_file = Path("internship_plan.csv")
        if plan_file.exists():
            try:
                with open(plan_file, "r", encoding="utf-8") as f:
                    plan_count = sum(1 for _ in csv.DictReader(f))
            except Exception:
                pass
                
    # 4. Profile refreshes total from statistics DB
    profile_refreshes_total = int(get_statistic("profile_refreshes_total", "0"))
    
    # 5. Recent applications from DB
    recent_applied = []
    try:
        rows = execute_query("SELECT job_id, title, company, score, resume, applied_at FROM applied_jobs ORDER BY applied_at DESC LIMIT 15")
        for row in rows:
            recent_applied.append({
                "job_id": row.get("job_id", ""),
                "title": row.get("title", ""),
                "company": row.get("company", ""),
                "score": str(row.get("score", "0")),
                "resume": row.get("resume", ""),
                "applied_at": row.get("applied_at", "")
            })
    except Exception:
        pass

    # 6. Read internship_plan.csv to see plan stats
    plan_jobs = []
    plan_file = Path("internship_plan.csv")
    if plan_file.exists():
        try:
            with open(plan_file, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    plan_jobs.append({
                        "job_id": row.get("job_id", ""),
                        "title": row.get("title", ""),
                        "company": row.get("company", ""),
                        "location": row.get("location", ""),
                        "score": row.get("score", "0"),
                        "resume": row.get("resume_profile", "")
                    })
        except Exception:
            pass
    plan_jobs = sorted(plan_jobs, key=lambda x: int(x["score"]), reverse=True)[:15]

    # Calculate optimal profile refresh analytics
    # Search appearances boost decay rate chart simulation
    decay_chart = [
        {"hours": 0, "boost": "15x (Immediate)", "relevance": 100, "status": "Peak Visibility"},
        {"hours": 12, "boost": "10x (High)", "relevance": 85, "status": "Search Front Page"},
        {"hours": 24, "boost": "5x (Moderate)", "relevance": 60, "status": "Search Inner Pages"},
        {"hours": 48, "boost": "2x (Low)", "relevance": 35, "status": "Search Decay Start"},
        {"hours": 72, "boost": "1x (Normal)", "relevance": 15, "status": "Recruiter Search Ignore"},
    ]

    # Fetch recent timeline alerts from DB
    timeline = get_timeline_events(50)

    return {
        "applied_total": applied_count,
        "applied_today": applied_today_count,
        "plan_total": plan_count,
        "profile_refreshes_total": profile_refreshes_total,
        "recent_applications": recent_applied,
        "top_planned_jobs": plan_jobs,
        "optimal_refresh_rate": "Daily (Recommended: Once every 24 Hours between 9 AM - 11 AM)",
        "optimal_refresh_reason": "Naukri search prioritizes profiles updated in the last 24 hours. Daily refresh keeps you active under the recruiter's 'Active in Last 24 Hours' filter.",
        "decay_chart": decay_chart,
        "timeline": timeline
    }


@app.post("/api/run")
def run_action(req: RunActionRequest):
    if not state.client or not state.client.naukri_session:
        raise HTTPException(status_code=401, detail="Naukri authentication required. Verify OTP first.")
        
    if state.running_task and state.running_task.is_alive():
        raise HTTPException(status_code=400, detail=f"Task {state.running_task_name} is already running.")

    if req.action == "plan":
        success = run_task_in_background("Internship Matcher Plan", run_internship_plan_flow, state.client)
    elif req.action == "apply":
        success = run_task_in_background("Internship Direct Apply", run_internship_apply_flow, state.client, req.confirm)
    elif req.action == "refresh":
        success = run_task_in_background("Naukri Profile Refresh", run_profile_refresh_flow, state.client, req.confirm)
    else:
        raise HTTPException(status_code=400, detail="Invalid action type.")

    if success:
        return {"success": True, "message": f"Successfully launched background task '{req.action}'."}
    else:
        return {"success": False, "message": "Failed to launch background task."}

@app.get("/api/logs")
def get_logs():
    daemon_log_path = Path("careerflow_assistant.log")
    daemon_logs = ""
    if daemon_log_path.exists():
        try:
            with open(daemon_log_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
                daemon_logs = "".join(lines[-150:])
        except Exception as e:
            daemon_logs = f"Error reading daemon logs: {e}\n"
            
    combined_logs = daemon_logs + "\n" + "".join(global_log_buffer)
    
    # Check if daemon is active
    daemon_active = False
    pid_path = Path("careerflow_daemon.pid")
    if pid_path.exists():
        try:
            with open(pid_path, "r") as f:
                pid = int(f.read().strip())
            os.kill(pid, 0)
            daemon_active = True
        except Exception:
            pass
            
    running_name = state.running_task_name
    if not running_name and daemon_active:
        running_name = "Autonomous Daemon (Active)"
        
    return {
        "running": running_name,
        "logs": combined_logs
    }

# ---------------------------------------------------------------------------
# AI Intelligence Endpoints
# ---------------------------------------------------------------------------

@app.get("/api/ai/status")
def ai_status():
    """Return the current AI engine configuration status."""
    return get_ai_status()

@app.post("/api/ai/generate-resume")
def ai_generate_resume(req: AIGenerateResumeRequest):
    """Generate tailored resume content for a specific job posting."""
    try:
        result = generate_tailored_resume(
            job_title=req.job_title,
            company=req.company,
            job_description=req.job_description,
            model=req.model or None,
        )
        if "error" in result:
            return {"success": False, "error": result["error"], "data": result}
        return {"success": True, "data": result}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/api/ai/optimize-headline")
def ai_optimize_headline(req: AIHeadlineRequest):
    """Generate an SEO-optimized Naukri headline."""
    try:
        result = generate_optimized_headline(
            target_role=req.target_role,
            current_headline=req.current_headline,
            model=req.model or None,
        )
        if "error" in result:
            return {"success": False, "error": result["error"], "data": result}
        return {"success": True, "data": result}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/api/ai/settings")
def ai_save_settings(req: AISettingsRequest):
    """Save OpenRouter API key and model preference."""
    changed = []
    if req.api_key:
        os.environ["OPENROUTER_API_KEY"] = req.api_key
        reset_ai_client()
        changed.append("API key")
    if req.model:
        os.environ["OPENROUTER_MODEL"] = req.model
        changed.append(f"Model → {req.model}")
    reload_knowledge()
    return {"success": True, "message": f"Updated: {', '.join(changed) or 'No changes'}"}

# Serve Static Frontend Files
frontend_dir = Path("src/dashboard/static")

@app.on_event("startup")
def startup_event():
    # 1. Initialize SQL Database and sync legacy CSV logs
    try:
        from src.careerflow.db import init_db, sync_legacy_csv_data, save_timeline_event
        init_db()
        sync_legacy_csv_data()
        save_timeline_event("Dashboard System Boot Success", "success")
    except Exception as e:
        print(f"[STARTUP ERROR] Database initialization failed: {e}")

    # 2. Spawn Keep-Alive Self-Ping thread if running on Render or custom URL configured
    external_url = (
        os.environ.get("RENDER_EXTERNAL_URL") or 
        os.environ.get("RENDER_APP_URL") or 
        os.environ.get("APP_URL")
    )
    if external_url:
        t = threading.Thread(target=keep_alive_ping, daemon=True)
        t.start()

    username = os.getenv("USERNAME")
    password = os.getenv("PASSWORD")
    if username and password and "your_naukri" not in username:
        print(f"[STARTUP] Found credentials in .env. Attempting automatic password login for {username}...")
        try:
            client = NaukriLoginClient(username, password)
            client.login()
            state.client = client
            state.mobile_number = username
            print("[STARTUP] ✅ Automatic login successful! Session is active.")
            try:
                from src.careerflow.db import save_timeline_event
                save_timeline_event(f"Automatic login successful for operator {username}", "success")
            except Exception:
                pass
        except Exception as e:
            print(f"[STARTUP] ⚠️ Automatic login failed: {e}. You can login manually via the dashboard.")
            try:
                from src.careerflow.db import save_timeline_event
                save_timeline_event(f"Automatic login failed for operator {username}", "error")
            except Exception:
                pass


if frontend_dir.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="static")
else:
    @app.get("/")
    def fallback_root():
        return HTMLResponse("<h2>Frontend static directory not found yet. Build index.html.</h2>")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8001))
    print("--------------------------------------------------")
    print("Launching CareerFlow AI Dashboard Server...")
    print(f"Open http://localhost:{port} in your browser to view.")
    print("--------------------------------------------------")
    uvicorn.run("server:app", host="0.0.0.0", port=port, log_level="info")
