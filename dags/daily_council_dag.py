from airflow import DAG
from airflow.operators.bash import BashOperator
from datetime import datetime, timedelta
import sys

sys.path.append('/opt/airflow')
from shared.airflow_utils import send_telegram_alert

default_args = {
    'owner': 'jennie',
    'depends_on_past': False,
    'retries': 0, # Council is expensive/complex, maybe don't auto-retry blindly?
    'on_failure_callback': send_telegram_alert,
}

# 17:30 KST -> 08:30 UTC
with DAG(
    'daily_council_v1',
    default_args=default_args,
    description='Daily Strategy Council (17:30 KST)',
    schedule_interval='30 8 * * *', 
    start_date=datetime(2025, 1, 1),
    catchup=False,
    tags=['council', 'strategy'],
) as dag:

    run_council = BashOperator(
        task_id='run_daily_council',
        bash_command='cd /opt/airflow && PYTHONPATH=/opt/airflow python scripts/run_daily_council.py',
    )
