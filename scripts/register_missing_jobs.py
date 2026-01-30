
import requests
import json
import os
import sys

# Add project root to path for imports if needed
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SCHEDULER_URL = "http://localhost:8095"  # Host-mapped port for scheduler-service (real profile)
SCOPE = "real"

def register_custom_jobs():
    jobs = [
        {
            "job_id": "collect-intraday",
            "description": "5분봉 데이터 수집 (09:00-15:35, 5분 간격)",
            "queue": f"{SCOPE}.jobs.data.intraday",
            "cron_expr": "*/5 9-15 * * 1-5", 
            "enabled": True,
            "reschedule_mode": "scheduler",
            "timeout_sec": 300,
            "default_params": {
                "script": "scripts/collect_intraday.py",
                "python_path": "python3" # Docker 내부 경로
            }
        },
        {
            "job_id": "daily-council",
            "description": "Daily Council (일일 전략 회의, 17:30)",
            "queue": f"{SCOPE}.jobs.council",
            "cron_expr": "30 17 * * *", 
            "enabled": True,
            "reschedule_mode": "scheduler",
            "timeout_sec": 1800, # 30분
            "default_params": {
                "script": "scripts/run_daily_council.py",
                 "python_path": "python3"
            }
        },
        # [NEW] Daily Prices (일봉 가격 데이터) - 매일 18:15
        {
            "job_id": "collect-daily-prices",
            "description": "Daily Stock Price Data (18:15)",
            "queue": f"{SCOPE}.jobs.data.trading", # worker.py가 듣고 있는 기존 큐(trading용) 활용 가능하나 명확성을 위해
            "cron_expr": "15 18 * * 1-5", 
            "enabled": True,
            "reschedule_mode": "scheduler",
            "timeout_sec": 1800,
            "default_params": {
                "python_path": "python3",
                "script": "scripts/collect_full_market_data_parallel.py"
            }
        },
        # [NEW] Investor Trading (외국인/기관 수급) - 매일 18:30
        {
            "job_id": "collect-trading",
            "description": "Daily Investor Trading Data (18:30)",
            "queue": f"{SCOPE}.jobs.data.trading",
            "cron_expr": "30 18 * * 1-5",  # 평일 18:30
            "enabled": True,
            "default_params": {
                "python_path": "python3",
                "script": "scripts/collect_investor_trading.py"
            }
        },
        # [NEW] DART Disclosures (공시) - 매일 18:45
        {
            "job_id": "collect-dart",
            "description": "Daily DART Filings (18:45)",
            "queue": f"{SCOPE}.jobs.data.dart",
            "cron_expr": "45 18 * * 1-5",  # 평일 18:45
            "enabled": True,
            "default_params": {
                "python_path": "python3",
                "script": "scripts/collect_dart_filings.py",
                "args": ["--days", "3", "--codes", "200"]
            }
        },
    ]

    print(f"🚀 Registering additional jobs to {SCHEDULER_URL}...")
    
    for job_def in jobs:
        try:
            print(f"Checking job '{job_def['job_id']}'...")
            # Check existence
            resp = requests.get(f"{SCHEDULER_URL}/jobs")
            
            if resp.status_code != 200:
                print(f"❌ Failed to connect: {resp.status_code} {resp.text}")
                continue
                
            existing_jobs = resp.json()
            exists = any(j['job_id'] == job_def['job_id'] for j in existing_jobs)
            
            if exists:
                print(f"🔄 Updating job: {job_def['job_id']}")
                # Update
                update_payload = {k: v for k, v in job_def.items() if k != "job_id"}
                resp = requests.put(f"{SCHEDULER_URL}/jobs/{job_def['job_id']}", json=update_payload)
            else:
                print(f"🆕 Creating job: {job_def['job_id']}")
                resp = requests.post(f"{SCHEDULER_URL}/jobs", json=job_def)
                
            if resp.status_code in (200, 201):
                print(f"✅ Success: {job_def['job_id']}")
            else:
                print(f"❌ Failed: {resp.status_code} - {resp.text}")
                
        except Exception as e:
            print(f"❌ Error: {e}")

if __name__ == "__main__":
    register_custom_jobs()
