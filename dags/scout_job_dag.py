from airflow import DAG
from airflow.operators.bash import BashOperator
from datetime import datetime, timedelta
import sys

sys.path.append('/opt/airflow')
from shared.airflow_utils import send_telegram_alert

default_args = {
    'owner': 'jennie',
    'depends_on_past': False,
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
    'on_failure_callback': send_telegram_alert,
}

# KST 08:30 - 15:30 (Every 30 mins)
# UTC: 23:30 (prev), 00:00, 00:30 ... 06:30
# Cron: "0,30 23,0-6 * * 1-5" (Approx)

with DAG(
    'scout_job_v1',
    default_args=default_args,
    description='AI Scout Job (Intraday)',
    schedule_interval='0,30 23,0-6 * * 1-5', 
    start_date=datetime(2025, 1, 1),
    catchup=False,
    tags=['scout', 'ai'],
) as dag:

    run_scout = BashOperator(
        task_id='run_scout_job',
        # service/scout-job has a main.py or similar entrypoint? 
        # Using "python services/scout-job/main.py"
        bash_command='cd /opt/airflow && PYTHONPATH=/opt/airflow python services/scout-job/main.py',
    )
