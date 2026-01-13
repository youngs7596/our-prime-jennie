from airflow import DAG
from airflow.operators.bash import BashOperator
from datetime import datetime, timedelta
import sys

sys.path.append('/opt/airflow')
from shared.airflow_utils import send_telegram_alert

default_args = {
    'owner': 'jennie',
    'depends_on_past': False,
    'retries': 3,
    'retry_delay': timedelta(minutes=1),
    'on_failure_callback': send_telegram_alert,
}

# Start: 09:00 KST -> 00:00 UTC
# Stop: 15:30 KST -> 06:30 UTC

with DAG(
    'price_monitor_ops',
    default_args=default_args,
    description='Price Monitor Start/Stop',
    schedule_interval='0 0 * * 1-5', # Default trigger for Start
    start_date=datetime(2025, 1, 1),
    catchup=False,
    tags=['price', 'monitor', 'ops'],
) as dag:

    # 1. Start Price Monitor Service (Container)
    # Ideally, we call an API or script that starts the service logic.
    # Referring to old scheduler: "price-monitor-start" job sends action="start" param.
    # Here we can run the script directly if it supports CLI
    start_monitor = BashOperator(
        task_id='start_price_monitor',
        bash_command='cd /opt/airflow && PYTHONPATH=/opt/airflow python services/price-monitor/main.py --action start',
    )
    
    # 2. Stop Price Monitor (Separate DAG)
    # 15:30 KST -> 06:30 UTC

with DAG(
    'price_monitor_stop_ops',
    default_args=default_args,
    description='Price Monitor Stop (15:30 KST)',
    schedule_interval='30 6 * * 1-5',
    start_date=datetime(2025, 1, 1),
    catchup=False,
    tags=['price', 'monitor', 'ops'],
) as dag_stop:

    stop_monitor = BashOperator(
        task_id='stop_price_monitor',
        bash_command='cd /opt/airflow && PYTHONPATH=/opt/airflow python services/price-monitor/main.py --action stop',
    )
