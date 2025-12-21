
import requests
import os
import sys

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SCHEDULER_URL = "http://localhost:8095" # Default port for scheduler service
# Need to match the scope defined in env vars, usually 'real'
SCOPE = "real" 
QUEUE_NAME = f"{SCOPE}.jobs.scout"

job_payload_feedback = {
    "job_id": "analyst-feedback-update",
    "description": "Daily Analyst Performance Feedback Generation",
    "queue": QUEUE_NAME,
    "cron_expr": "0 18 * * 1-5", # Weekdays (Mon-Fri) at 18:00 KST
    "enabled": True,
    "reschedule_mode": "scheduler",
    "timeout_sec": 300, # 5 minutes
    "default_params": {}
}

def register_job(job_data):
    try:
        # Check if job exists
        print(f"Checking existing jobs from {SCHEDULER_URL}...")
        resp = requests.get(f"{SCHEDULER_URL}/jobs")
        if resp.status_code != 200:
            print(f"❌ Failed to connect to Scheduler: {resp.text}")
            return

        existing_jobs = resp.json()
        exists = any(j['job_id'] == job_data['job_id'] for j in existing_jobs)
        
        if exists:
            print(f"🔄 Updating job: {job_data['job_id']}")
            # Update endpoint is PUT /jobs/{job_id}
            # Note: API expects partial update in JobUpdate schema
            update_payload = {k: v for k, v in job_data.items() if k != "job_id"}
            resp = requests.put(f"{SCHEDULER_URL}/jobs/{job_data['job_id']}", json=update_payload)
        else:
            print(f"🆕 Creating job: {job_data['job_id']}")
            # Create endpoint is POST /jobs
            # Note: JobCreate schema requires job_id inside body
            resp = requests.post(f"{SCHEDULER_URL}/jobs", json=job_data)
            
        if resp.status_code in (200, 201):
            print(f"✅ Success: {resp.json()['job_id']} scheduled at {job_data['cron_expr']}")
        else:
            print(f"❌ Failed: {resp.status_code} - {resp.text}")
            
    except Exception as e:
        print(f"❌ Error registering job {job_data['job_id']}: {e}")

if __name__ == "__main__":
    register_job(job_payload_feedback)
