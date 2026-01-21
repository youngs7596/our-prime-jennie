
import requests
import os
import sys

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SCHEDULER_URL = "http://localhost:8091" # Scheduler Service internal port
# Need to match the scope defined in env vars, usually 'real'
SCOPE = os.getenv("SCHEDULER_SCOPE", "real")

def get_jobs_config():
    return [
        {
            "job_id": "scout-job",
            "description": "AI Scout Job (30m interval)",
            "queue": f"{SCOPE}.jobs.scout",
            "cron_expr": "*/30 * * * *",
            "enabled": True,
            "reschedule_mode": "scheduler",
            "timeout_sec": 600,
            "default_params": {}
        },

        {
            "job_id": "price-monitor-pulse",
            "description": "Price Monitor Pulse (Keep-Alive)",
            "queue": f"{SCOPE}.jobs.price-monitor",
            "cron_expr": "*/5 9-15 * * 1-5", # 09:00 - 15:55 Mon-Fri
            "enabled": True,
            "reschedule_mode": "scheduler",
            "timeout_sec": 60,
            "default_params": {"action": "pulse"}
        }
    ]

def register_job(job_data):
    try:
        # Check if job exists
        print(f"Checking job '{job_data['job_id']}'...")
        resp = requests.get(f"{SCHEDULER_URL}/jobs")
        
        if resp.status_code != 200:
            print(f"❌ Failed to connect to Scheduler: {resp.text}")
            return

        existing_jobs = resp.json()
        exists = any(j['job_id'] == job_data['job_id'] for j in existing_jobs)
        
        if exists:
            print(f"🔄 Updating job: {job_data['job_id']}")
            # Update endpoint is PUT /jobs/{job_id}
            update_payload = {k: v for k, v in job_data.items() if k != "job_id"}
            resp = requests.put(f"{SCHEDULER_URL}/jobs/{job_data['job_id']}", json=update_payload)
        else:
            print(f"🆕 Creating job: {job_data['job_id']}")
            resp = requests.post(f"{SCHEDULER_URL}/jobs", json=job_data)
            
        if resp.status_code in (200, 201):
            print(f"✅ Success: {job_data['job_id']} scheduled at '{job_data['cron_expr']}'")
        else:
            print(f"❌ Failed: {resp.status_code} - {resp.text}")
            
    except Exception as e:
        print(f"❌ Error registering job {job_data['job_id']}: {e}")

if __name__ == "__main__":
    print(f"🚀 Registering default jobs for SCOPE={SCOPE}...")
    for job in get_jobs_config():
        register_job(job)
