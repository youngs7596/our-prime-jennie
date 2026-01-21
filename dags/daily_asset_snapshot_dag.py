from airflow import DAG
from airflow.operators.bash import BashOperator
from datetime import datetime, timedelta
import sys
import pendulum

# KST timezone setting
local_tz = pendulum.timezone("Asia/Seoul")

default_args = {
    'owner': 'jennie',
    'depends_on_past': False,
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
}

# Common Environment Variables (Docker 네트워크 내 서비스 접근용)
COMMON_ENV = {
    'PYTHONPATH': '/opt/airflow',
    'MARIADB_HOST': 'mariadb',
    'MARIADB_PORT': '3306',
    'MARIADB_USER': 'root',
    'REDIS_HOST': 'redis',
    'REDIS_PORT': '6379',
    'KIS_GATEWAY_URL': 'http://host.docker.internal:8080',
    'TZ': 'Asia/Seoul',
}

# Schedule: 15:45 KST (Market Close + Settlement Time)
# UTC: 06:45
with DAG(
    'daily_asset_snapshot',
    default_args=default_args,
    description='Daily Asset Snapshot (Total Asset, Cash, Stock Eval)',
    schedule_interval='45 6 * * 1-5', # 06:45 UTC = 15:45 KST
    start_date=datetime(2025, 1, 1, tzinfo=local_tz),
    catchup=False,
    tags=['asset', 'snapshot', 'statistics'],
) as dag:

    # Run the snapshot script
    # Assuming the project root is mounted at /opt/airflow
    # {{ ds }} is execution date (YYYY-MM-DD)
    run_snapshot = BashOperator(
        task_id='run_snapshot_script',
        bash_command='cd /opt/airflow && PYTHONPATH=/opt/airflow python3 scripts/daily_asset_snapshot.py --date {{ ds }}',
        env=COMMON_ENV,
    )
