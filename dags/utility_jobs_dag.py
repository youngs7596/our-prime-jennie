
from airflow import DAG
from airflow.operators.bash import BashOperator
from datetime import datetime, timedelta
import sys
import os

# Add airflow root to path for shared imports if needed
sys.path.append('/opt/airflow')
from shared.airflow_utils import send_telegram_alert

import pendulum

kst = pendulum.timezone("Asia/Seoul")

default_args = {
    'owner': 'jennie',
    'depends_on_past': False,
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
    'on_failure_callback': send_telegram_alert,
}

# Common Environment Variables
# DB & Redis services are in the same bridge network (msa-network), so we use service names.
# KIS Gateway & Ollama Gateway are on the host network, so we use host.docker.internal (requires extra_hosts in docker-compose).
COMMON_ENV = {
    'PYTHONPATH': '/opt/airflow',
    'MARIADB_HOST': 'mariadb',
    'MARIADB_PORT': '3306',
    'MARIADB_USER': 'jennie',
    'MARIADB_PASSWORD': 'q1w2e3R$',
    'MARIADB_DBNAME': 'jennie_db',
    'REDIS_HOST': 'redis',
    'REDIS_PORT': '6379',
    'KIS_GATEWAY_URL': 'http://host.docker.internal:8080',
    'OLLAMA_GATEWAY_URL': 'http://host.docker.internal:11500',
    'TZ': 'Asia/Seoul',
}

# KST Schedules
# 1. Collect Intraday Prices: 09:00 - 15:35 KST. 5 min interval.
with DAG(
    'collect_intraday',
    default_args=default_args,
    schedule_interval='*/5 9-15 * * 1-5', # KST explicitly
    start_date=datetime(2025, 1, 1, tzinfo=kst),
    catchup=False,
    tags=['data', 'intraday', 'price'],
) as dag_intraday:
    run_intraday = BashOperator(
        task_id='run_collect_intraday',
        bash_command='python scripts/collect_intraday.py',
        cwd='/opt/airflow',
        env=COMMON_ENV,
    )

# 2. Analyst Feedback Update: 18:00 KST
with DAG(
    'analyst_feedback_update',
    default_args=default_args,
    schedule_interval='0 18 * * 1-5', # 18:00 KST
    start_date=datetime(2025, 1, 1, tzinfo=kst),
    catchup=False,
    tags=['analysis', 'feedback', 'llm'],
) as dag_feedback:
    run_feedback = BashOperator(
        task_id='run_update_analyst_feedback',
        bash_command='python scripts/update_analyst_feedback.py',
        cwd='/opt/airflow',
        env=COMMON_ENV,
    )

# 3. Collect Daily Prices (FDR): 18:15 KST
with DAG(
    'collect_daily_prices',
    default_args=default_args,
    schedule_interval='15 18 * * 1-5', # 18:15 KST
    start_date=datetime(2025, 1, 1, tzinfo=kst),
    catchup=False,
    tags=['data', 'daily', 'price'],
) as dag_daily_price:
    run_daily_price = BashOperator(
        task_id='run_collect_prices_fdr',
        bash_command='python scripts/collect_prices_fdr.py',
        cwd='/opt/airflow',
        env=COMMON_ENV,
        execution_timeout=timedelta(minutes=30),  # 951개 종목 처리에 충분한 시간
    )

# 4. Collect Investor Trading: 18:30 KST
with DAG(
    'collect_investor_trading',
    default_args=default_args,
    schedule_interval='30 18 * * 1-5', # 18:30 KST
    start_date=datetime(2025, 1, 1, tzinfo=kst),
    catchup=False,
    tags=['data', 'investor', 'trading'],
) as dag_trading:
    run_trading = BashOperator(
        task_id='run_collect_investor_trading',
        bash_command='python scripts/collect_investor_trading.py',
        cwd='/opt/airflow',
        env=COMMON_ENV,
    )

# 5. Collect DART Filings: 18:45 KST
with DAG(
    'collect_dart_filings',
    default_args=default_args,
    schedule_interval='45 18 * * 1-5', # 18:45 KST
    start_date=datetime(2025, 1, 1, tzinfo=kst),
    catchup=False,
    tags=['data', 'dart', 'filings'],
) as dag_dart:
    run_dart = BashOperator(
        task_id='run_collect_dart_filings',
        bash_command='python scripts/collect_dart_filings.py',
        cwd='/opt/airflow',
        env=COMMON_ENV,
    )

# 6. Data Cleanup (Weekly): 03:00 KST on Sunday
# 보관 정책: NEWS_SENTIMENT(30일), STOCK_MINUTE_PRICE(7일), LLM_DECISION_LEDGER(90일) 등
with DAG(
    'data_cleanup_weekly',
    default_args=default_args,
    schedule_interval='0 3 * * 0',  # 매주 일요일 03:00 KST
    start_date=datetime(2025, 1, 1, tzinfo=kst),
    catchup=False,
    tags=['maintenance', 'cleanup', 'retention'],
) as dag_cleanup:
    run_cleanup = BashOperator(
        task_id='run_cleanup_old_data',
        bash_command='python scripts/cleanup_old_data.py',
        cwd='/opt/airflow',
        env=COMMON_ENV,
    )
