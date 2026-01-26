from airflow import DAG
from airflow.operators.bash import BashOperator
from datetime import datetime, timedelta
import sys

sys.path.append('/opt/airflow')
from shared.airflow_utils import send_telegram_alert

import pendulum

kst = pendulum.timezone("Asia/Seoul")

default_args = {
    'owner': 'jennie',
    'depends_on_past': False,
    'retries': 3,
    'retry_delay': timedelta(minutes=1),
    'on_failure_callback': send_telegram_alert,
}

# Start: 09:00 KST
# Stop: 15:30 KST

with DAG(
    'price_monitor_ops',
    default_args=default_args,
    description='Price Monitor Start/Stop',
    schedule_interval='0 9 * * 1-5', # 09:00 KST
    start_date=datetime(2025, 1, 1, tzinfo=kst),
    catchup=False,
    tags=['price', 'monitor', 'ops'],
) as dag:

    # 1. Start Price Monitor Service (Trigger API)
    # price-monitor is on host network port 8088
    start_monitor = BashOperator(
        task_id='start_price_monitor',
        bash_command='curl -X POST http://host.docker.internal:8088/start',
    )
    
    # 2. Stop Price Monitor (Separate DAG)
    # 15:30 KST

with DAG(
    'price_monitor_stop_ops',
    default_args=default_args,
    description='Price Monitor Stop (15:30 KST)',
    schedule_interval='30 15 * * 1-5', # 15:30 KST
    start_date=datetime(2025, 1, 1, tzinfo=kst),
    catchup=False,
    tags=['price', 'monitor', 'ops'],
) as dag_stop:

    stop_monitor = BashOperator(
        task_id='stop_price_monitor',
        bash_command='curl -X POST http://host.docker.internal:8088/stop',
    )
