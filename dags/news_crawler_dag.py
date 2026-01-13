from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.operators.python import PythonOperator
from datetime import datetime, timedelta
import sys
import os

# Custom Alerts
sys.path.append('/opt/airflow')
from shared.airflow_utils import send_telegram_alert

default_args = {
    'owner': 'jennie',
    'depends_on_past': False,
    'email_on_failure': False,
    'email_on_retry': False,
    'retries': 3,
    'retry_delay': timedelta(minutes=5),
    'on_failure_callback': send_telegram_alert, # Critical: Connect Failure Callback
}

with DAG(
    'news_crawler_v1',
    default_args=default_args,
    description='News Crawler (07, 15, 16 KST)',
    schedule_interval='0 22,6,7 * * *', 
    start_date=datetime(2025, 1, 1),
    catchup=False,
    tags=['crawler', 'news'],
) as dag:

    # Docker container executes this. 
    # Must ensure PYTHONPATH includes project root
    run_crawler = BashOperator(
        task_id='run_news_crawler',
        bash_command='cd /opt/airflow && PYTHONPATH=/opt/airflow python services/news-crawler/main.py',
    )
