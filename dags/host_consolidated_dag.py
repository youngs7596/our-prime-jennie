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
    'retries': 2,
    'retry_delay': timedelta(minutes=5),
    'on_failure_callback': send_telegram_alert,
}

# 1. Weekly Factor Analysis (Friday 22:00 KST)
with DAG(
    'weekly_factor_analysis',
    default_args=default_args,
    schedule_interval='0 22 * * 5', # 22:00 KST
    start_date=datetime(2025, 1, 1, tzinfo=kst),
    catchup=False,
    tags=['analysis', 'factor', 'weekly'],
) as dag_weekly:
    run_analysis = BashOperator(
        task_id='run_factor_analysis',
        bash_command='curl -sf --max-time 1800 -X POST http://job-worker:8095/jobs/weekly-factor-analysis',
    )

# 2. Daily Price Collector (Weekday 16:00 KST)
with DAG(
    'daily_market_data_collector',
    default_args=default_args,
    schedule_interval='0 16 * * 1-5', # 16:00 KST
    start_date=datetime(2025, 1, 1, tzinfo=kst),
    catchup=False,
    tags=['data', 'collector', 'daily'],
) as dag_collector:
    run_collector = BashOperator(
        task_id='collect_full_market_data',
        bash_command='curl -sf --max-time 600 -X POST http://job-worker:8095/jobs/collect-full-market-data',
    )

# 3. Daily Briefing (Weekday 17:00 KST) - 이미 HTTP 트리거 (변경 불필요)
with DAG(
    'daily_briefing_report',
    default_args=default_args,
    schedule_interval='0 17 * * 1-5', # 17:00 KST
    start_date=datetime(2025, 1, 1, tzinfo=kst),
    catchup=False,
    tags=['briefing', 'report'],
) as dag_briefing:
    trigger_briefing = BashOperator(
        task_id='trigger_briefing_api',
        bash_command='curl -s -X POST http://host.docker.internal:8086/report',
    )

# 4. AI Performance Analysis (Weekday 07:00 KST)
with DAG(
    'daily_ai_performance_analysis',
    default_args=default_args,
    schedule_interval='0 7 * * 1-5', # 07:00 KST
    start_date=datetime(2025, 1, 1, tzinfo=kst),
    catchup=False,
    tags=['analysis', 'ai', 'performance'],
) as dag_ai_perf:
    run_ai_perf = BashOperator(
        task_id='analyze_ai_performance',
        bash_command='curl -sf --max-time 300 -X POST http://job-worker:8095/jobs/analyze-ai-performance',
    )
