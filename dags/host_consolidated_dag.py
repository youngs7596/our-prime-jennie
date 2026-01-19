from airflow import DAG
from airflow.operators.bash import BashOperator
from datetime import datetime, timedelta
import sys

sys.path.append('/opt/airflow')
from shared.airflow_utils import send_telegram_alert

default_args = {
    'owner': 'jennie',
    'depends_on_past': False,
    'retries': 2,
    'retry_delay': timedelta(minutes=5),
    'on_failure_callback': send_telegram_alert,
}

# Common Environment Variables (Same as utility_jobs_dag)
COMMON_ENV = {
    'PYTHONPATH': '/opt/airflow',
    'MARIADB_HOST': 'mariadb',
    'MARIADB_PORT': '3306',
    'MARIADB_USER': 'root',
    'REDIS_HOST': 'redis',
    'REDIS_PORT': '6379',
    'KIS_GATEWAY_URL': 'http://host.docker.internal:8080',
    'OLLAMA_GATEWAY_URL': 'http://host.docker.internal:11500',
    'TZ': 'Asia/Seoul',
}

# 1. Weekly Factor Analysis (Friday 22:00 KST -> 13:00 UTC)
with DAG(
    'weekly_factor_analysis',
    default_args=default_args,
    schedule_interval='0 13 * * 5',
    start_date=datetime(2025, 1, 1),
    catchup=False,
    tags=['analysis', 'factor', 'weekly'],
) as dag_weekly:
    run_analysis = BashOperator(
        task_id='run_factor_analysis',
        bash_command='export MARIADB_HOST=mariadb && export MARIADB_PORT=3306 && export MARIADB_USER=root && cd /opt/airflow && PYTHONPATH=/opt/airflow python scripts/weekly_factor_analysis_batch.py',
        env=COMMON_ENV,
    )

# 2. Daily Price Collector (Weekday 16:00 KST -> 07:00 UTC)
with DAG(
    'daily_market_data_collector',
    default_args=default_args,
    schedule_interval='0 7 * * 1-5',
    start_date=datetime(2025, 1, 1),
    catchup=False,
    tags=['data', 'collector', 'daily'],
) as dag_collector:
    run_collector = BashOperator(
        task_id='collect_full_market_data',
        bash_command='cd /opt/airflow && PYTHONPATH=/opt/airflow python scripts/collect_full_market_data_parallel.py',
        env=COMMON_ENV,
    )

# 3. Daily Briefing (Weekday 17:00 KST -> 08:00 UTC)
with DAG(
    'daily_briefing_report',
    default_args=default_args,
    schedule_interval='0 8 * * 1-5',
    start_date=datetime(2025, 1, 1),
    catchup=False,
    tags=['briefing', 'report'],
) as dag_briefing:
    # This calls the service API. Inside Docker network, use service name.
    # Host crontab used localhost:8086, inside docker it is http://daily-briefing:8086
    trigger_briefing = BashOperator(
        task_id='trigger_briefing_api',
        bash_command='curl -s -X POST http://host.docker.internal:8086/report',
    )

# 4. AI Performance Analysis (Weekday 07:00 KST -> 22:00 UTC Prev Day)
with DAG(
    'daily_ai_performance_analysis',
    default_args=default_args,
    schedule_interval='0 22 * * 0-4',
    start_date=datetime(2025, 1, 1),
    catchup=False,
    tags=['analysis', 'ai', 'performance'],
) as dag_ai_perf:
    run_ai_perf = BashOperator(
        task_id='analyze_ai_performance',
        bash_command='cd /opt/airflow && PYTHONPATH=/opt/airflow python scripts/analyze_ai_performance.py',
        env=COMMON_ENV,
    )
