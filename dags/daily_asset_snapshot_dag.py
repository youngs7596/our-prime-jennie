from airflow import DAG
from airflow.operators.bash import BashOperator
from datetime import datetime, timedelta
import sys
import pendulum

sys.path.append('/opt/airflow')
from shared.airflow_utils import send_telegram_alert

# KST timezone setting
local_tz = pendulum.timezone("Asia/Seoul")

default_args = {
    'owner': 'jennie',
    'depends_on_past': False,
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
    'on_failure_callback': send_telegram_alert,
}

# Schedule: 15:45 KST (Market Close + Settlement Time)
with DAG(
    'daily_asset_snapshot',
    default_args=default_args,
    description='Daily Asset Snapshot (Total Asset, Cash, Stock Eval)',
    schedule_interval='45 15 * * 1-5', # 15:45 KST
    start_date=datetime(2025, 1, 1, tzinfo=local_tz),
    catchup=False,
    tags=['asset', 'snapshot', 'statistics'],
) as dag:

    # {{ ds }} is Airflow execution date (YYYY-MM-DD), passed as query param
    run_snapshot = BashOperator(
        task_id='run_snapshot_script',
        bash_command='curl -sf --max-time 300 -X POST "http://job-worker:8095/jobs/daily-asset-snapshot?date={{ ds }}"',
    )
