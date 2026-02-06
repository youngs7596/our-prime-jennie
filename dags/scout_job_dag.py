from airflow import DAG
from airflow.operators.bash import BashOperator
from datetime import datetime, timedelta
import sys
import pendulum

sys.path.append('/opt/airflow')
from shared.airflow_utils import send_telegram_alert

kst = pendulum.timezone("Asia/Seoul")

default_args = {
    'owner': 'jennie',
    'depends_on_past': False,
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
    'on_failure_callback': send_telegram_alert,
}

# KST 08:30 - 15:30 (Every 1 hour) - 비용 최적화: 30분→1시간
# Mon-Fri (1-5) in KST
with DAG(
    'scout_job_v1',
    default_args=default_args,
    description='AI Scout Job (Intraday)',
    schedule_interval='30 8-15 * * 1-5',
    start_date=datetime(2025, 1, 1, tzinfo=kst),
    catchup=False,
    tags=['scout', 'ai'],
) as dag:

    run_scout = BashOperator(
        task_id='run_scout_job',
        # Trigger the existing scout-job service via HTTP API
        # scout-job is on host network port 8087, accessed via host.docker.internal from container
        bash_command='curl -X POST -H "Content-Type: application/json" http://host.docker.internal:8087/scout',
    )
