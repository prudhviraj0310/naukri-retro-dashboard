import os
import sqlite3
import urllib.parse
from datetime import datetime

# Check if PostgreSQL DATABASE_URL is available
DATABASE_URL = os.environ.get("DATABASE_URL")

def get_db_connection():
    if DATABASE_URL:
        import psycopg2
        return psycopg2.connect(DATABASE_URL)
    else:
        # Fallback to local SQLite database in workspace
        db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "careerflow.db")
        conn = sqlite3.connect(db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

def execute_query(query, params=None):
    if params is None:
        params = ()
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Translate ? placeholders to %s if using PostgreSQL
    if DATABASE_URL:
        query = query.replace("?", "%s")
        
    try:
        cursor.execute(query, params)
        if query.strip().upper().startswith("SELECT"):
            columns = [col[0] for col in cursor.description]
            rows = cursor.fetchall()
            
            # Convert SQLite Row or Postgres tuple to standard dictionaries
            result = []
            for row in rows:
                result.append(dict(zip(columns, row)))
            return result
        else:
            conn.commit()
            return cursor.rowcount
    except Exception as e:
        print(f"[DATABASE ERROR] Query execution failed: {e}")
        print(f"               Query: {query}")
        raise e
    finally:
        cursor.close()
        conn.close()

def init_db():
    print("[DATABASE] Initializing persistent data tables...")
    id_type = "SERIAL PRIMARY KEY" if DATABASE_URL else "INTEGER PRIMARY KEY AUTOINCREMENT"
    
    # 1. Create applied_jobs table
    execute_query(f"""
        CREATE TABLE IF NOT EXISTS applied_jobs (
            job_id TEXT PRIMARY KEY,
            title TEXT,
            company TEXT,
            score INTEGER,
            applied_at TEXT,
            resume TEXT
        )
    """)
    
    # 2. Create timeline_events table
    execute_query(f"""
        CREATE TABLE IF NOT EXISTS timeline_events (
            id {id_type},
            message TEXT,
            type TEXT,
            time TEXT
        )
    """)
    
    # 3. Create statistics table
    execute_query(f"""
        CREATE TABLE IF NOT EXISTS statistics (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    
    # 4. Create naukri_sessions table
    execute_query(f"""
        CREATE TABLE IF NOT EXISTS naukri_sessions (
            username TEXT PRIMARY KEY,
            token TEXT,
            cookies TEXT,
            updated_at TEXT
        )
    """)
    
    # 5. Initialize default statistics values
    if DATABASE_URL:
        # PostgreSQL syntax
        execute_query("INSERT INTO statistics (key, value) VALUES ('profile_refreshes_total', '0') ON CONFLICT DO NOTHING")
        execute_query("INSERT INTO statistics (key, value) VALUES ('last_refresh_run', 'Never') ON CONFLICT DO NOTHING")
        execute_query("INSERT INTO statistics (key, value) VALUES ('plan_total', '0') ON CONFLICT DO NOTHING")
    else:
        # SQLite syntax
        execute_query("INSERT OR IGNORE INTO statistics (key, value) VALUES ('profile_refreshes_total', '0')")
        execute_query("INSERT OR IGNORE INTO statistics (key, value) VALUES ('last_refresh_run', 'Never')")
        execute_query("INSERT OR IGNORE INTO statistics (key, value) VALUES ('plan_total', '0')")
        
    print("[DATABASE] ✅ Persistent tables initialized successfully!")

# Seed functions to sync legacy CSV data on first boot if database is empty
def sync_legacy_csv_data():
    try:
        # Check if already seeded
        jobs_count = execute_query("SELECT COUNT(*) as c FROM applied_jobs")[0]["c"]
        if jobs_count > 0:
            return # Already seeded
            
        # Parse applied_jobs.csv / internship_applications.csv
        applications_file = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "internship_applications.csv")
        if os.path.exists(applications_file):
            print("[DATABASE] Legacy CSV detected. Seeding applications into cloud database...")
            import csv
            with open(applications_file, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    job_id = row.get("job_id", "")
                    if not job_id:
                        continue
                    # Insert ignoring conflicts
                    if DATABASE_URL:
                        execute_query("""
                            INSERT INTO applied_jobs (job_id, title, company, score, applied_at, resume)
                            VALUES (?, ?, ?, ?, ?, ?)
                            ON CONFLICT (job_id) DO NOTHING
                        """, (
                            job_id,
                            row.get("title", "Unknown"),
                            row.get("company", "Unknown"),
                            int(row.get("score", 0) or 0),
                            row.get("applied_at", datetime.utcnow().isoformat()),
                            row.get("resume_profile", "Unknown")
                        ))
                    else:
                        execute_query("""
                            INSERT OR IGNORE INTO applied_jobs (job_id, title, company, score, applied_at, resume)
                            VALUES (?, ?, ?, ?, ?, ?)
                        """, (
                            job_id,
                            row.get("title", "Unknown"),
                            row.get("company", "Unknown"),
                            int(row.get("score", 0) or 0),
                            row.get("applied_at", datetime.utcnow().isoformat()),
                            row.get("resume_profile", "Unknown")
                        ))
            print("[DATABASE] ✅ Seeding from legacy CSV complete!")
    except Exception as e:
        print("[DATABASE WARNING] Failed to seed legacy CSV: {e}")

def get_statistic(key, default="0"):
    try:
        res = execute_query("SELECT value FROM statistics WHERE key = ?", (key,))
        if res:
            return res[0]["value"]
    except Exception as e:
        print(f"[DATABASE WARNING] Failed to fetch statistic '{key}': {e}")
    return default

def set_statistic(key, value):
    try:
        if DATABASE_URL:
            execute_query("""
                INSERT INTO statistics (key, value) 
                VALUES (?, ?) 
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
            """, (key, str(value)))
        else:
            execute_query("""
                INSERT OR REPLACE INTO statistics (key, value) 
                VALUES (?, ?)
            """, (key, str(value)))
    except Exception as e:
        print(f"[DATABASE ERROR] Failed to set statistic '{key}' = '{value}': {e}")

def increment_statistic(key):
    try:
        val = int(get_statistic(key, "0")) + 1
        set_statistic(key, str(val))
    except Exception as e:
        print(f"[DATABASE ERROR] Failed to increment statistic '{key}': {e}")

def save_applied_job_to_db(job_id, title, company, score, resume_profile):
    try:
        applied_at = datetime.utcnow().isoformat()
        if DATABASE_URL:
            execute_query("""
                INSERT INTO applied_jobs (job_id, title, company, score, applied_at, resume)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT (job_id) DO UPDATE SET
                    title = EXCLUDED.title,
                    company = EXCLUDED.company,
                    score = EXCLUDED.score,
                    applied_at = EXCLUDED.applied_at,
                    resume = EXCLUDED.resume
            """, (job_id, title, company, int(score or 0), applied_at, resume_profile))
        else:
            execute_query("""
                INSERT OR REPLACE INTO applied_jobs (job_id, title, company, score, applied_at, resume)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (job_id, title, company, int(score or 0), applied_at, resume_profile))
    except Exception as e:
        print(f"[DATABASE ERROR] Failed to save applied job '{job_id}' to DB: {e}")

def save_timeline_event(message, type_):
    try:
        time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        execute_query("""
            INSERT INTO timeline_events (message, type, time)
            VALUES (?, ?, ?)
        """, (message, type_, time_str))
    except Exception as e:
        print(f"[DATABASE ERROR] Failed to save timeline event '{message}': {e}")

def get_timeline_events(limit=50):
    try:
        return execute_query("SELECT message, type, time FROM timeline_events ORDER BY id DESC LIMIT ?", (limit,))
    except Exception as e:
        print(f"[DATABASE WARNING] Failed to retrieve timeline events: {e}")
        return []

def save_naukri_session(username, token, cookies_dict):
    try:
        import json
        cookies_json = json.dumps(cookies_dict)
        # Clean existing sessions for the same user
        execute_query("DELETE FROM naukri_sessions WHERE username = ?", (username,))
        # Insert new session
        execute_query("""
            INSERT INTO naukri_sessions (username, token, cookies, updated_at)
            VALUES (?, ?, ?, ?)
        """, (username, token, cookies_json, datetime.now().isoformat()))
        print(f"[DATABASE] Saved authenticated session for {username}.")
    except Exception as e:
        print(f"[DATABASE ERROR] Failed to save session for {username}: {e}")

def load_latest_naukri_session():
    try:
        rows = execute_query("SELECT username, token, cookies FROM naukri_sessions ORDER BY updated_at DESC LIMIT 1")
        if rows:
            import json
            row = rows[0]
            try:
                cookies_dict = json.loads(row["cookies"])
            except Exception:
                cookies_dict = {}
            return {
                "username": row["username"],
                "token": row["token"],
                "cookies": cookies_dict
            }
    except Exception as e:
        print(f"[DATABASE WARNING] Failed to load latest session: {e}")
    return None

