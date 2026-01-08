import os
import sys
import json
import time
import logging
import subprocess
import signal
from typing import Dict

# Add shared to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.rabbitmq import RabbitMQWorker
from shared import auth

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("scheduler-worker")

# Configuration
RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@rabbitmq:5672/")
SCHEDULER_SCOPE = os.getenv("SCHEDULER_SCOPE", "real")

# List of queues to consume
QUEUES = [
    f"{SCHEDULER_SCOPE}.jobs.data.intraday",
    f"{SCHEDULER_SCOPE}.jobs.data.trading",
    f"{SCHEDULER_SCOPE}.jobs.data.dart",
]

workers = []

def execute_job(payload: Dict):
    """Execute the job script specified in the payload"""
    job_id = payload.get("job_id")
    params = payload.get("params", {})
    
    script_path = params.get("script")
    if not script_path:
        logger.error(f"❌ Job {job_id}: No script specified in params")
        return

    # Check if script exists
    full_path = os.path.join("/app", script_path)
    if not os.path.exists(full_path):
        logger.error(f"❌ Job {job_id}: Script not found at {full_path}")
        return

    logger.info(f"🚀 Starting Job {job_id}: {script_path}")
    
    # Build command
    cmd = ["python3", full_path]
    args = params.get("args", [])
    if isinstance(args, list):
        cmd.extend(args)
    
    start_time = time.time()
    try:
        # Run process
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=params.get("timeout_sec", 300) # Default timeout from job not payload, but payload has it too usually
        )
        
        duration = time.time() - start_time
        
        if result.returncode == 0:
            logger.info(f"✅ Job {job_id} finished successfully in {duration:.2f}s")
            if result.stdout:
                logger.info(f"[{job_id} STDOUT]\n{result.stdout}")
        else:
            logger.error(f"❌ Job {job_id} failed in {duration:.2f}s with code {result.returncode}")
            if result.stderr:
                logger.error(f"[{job_id} STDERR]\n{result.stderr}")
                
    except subprocess.TimeoutExpired:
        logger.error(f"⏱️ Job {job_id} timed out after {time.time() - start_time:.2f}s")
    except Exception as e:
        logger.exception(f"❌ Job {job_id} execution error: {e}")

def main():
    logger.info(f"Starting Scheduler Worker for scope: {SCHEDULER_SCOPE}")
    logger.info(f"Listening on queues: {QUEUES}")
    
    for queue in QUEUES:
        worker = RabbitMQWorker(RABBITMQ_URL, queue, execute_job)
        worker.start()
        workers.append(worker)
        
    # Wait for interrupt
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Stopping workers...")
        for w in workers:
            w.stop()

if __name__ == "__main__":
    main()
