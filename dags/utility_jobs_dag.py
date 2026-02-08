
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
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
    'on_failure_callback': send_telegram_alert,
}

# 1. Collect Minute Chart Data: 09:00 - 15:35 KST. 5 min interval.
with DAG(
    'collect_minute_chart',
    default_args=default_args,
    schedule_interval='*/5 9-15 * * 1-5',
    start_date=datetime(2025, 1, 1, tzinfo=kst),
    catchup=False,
    tags=['data', 'intraday', 'chart'],
) as dag_intraday:
    run_intraday = BashOperator(
        task_id='run_collect_minute_chart',
        bash_command='curl -sf --max-time 300 -X POST http://job-worker:8095/jobs/collect-minute-chart',
    )

# 2. Analyst Feedback Update: 18:00 KST
with DAG(
    'analyst_feedback_update',
    default_args=default_args,
    schedule_interval='0 18 * * 1-5',
    start_date=datetime(2025, 1, 1, tzinfo=kst),
    catchup=False,
    tags=['analysis', 'feedback', 'llm'],
) as dag_feedback:
    run_feedback = BashOperator(
        task_id='run_update_analyst_feedback',
        bash_command='curl -sf --max-time 120 -X POST http://job-worker:8095/jobs/analyst-feedback',
    )

# 3. (삭제됨) collect_daily_prices - daily_market_data_collector(KIS API, 16:00)와 중복으로 제거

# 4. Collect Investor Trading: 18:30 KST
with DAG(
    'collect_investor_trading',
    default_args=default_args,
    schedule_interval='30 18 * * 1-5',
    start_date=datetime(2025, 1, 1, tzinfo=kst),
    catchup=False,
    tags=['data', 'investor', 'trading'],
) as dag_trading:
    run_trading = BashOperator(
        task_id='run_collect_investor_trading',
        bash_command='curl -sf --max-time 600 -X POST http://job-worker:8095/jobs/collect-investor-trading',
    )

# 5. Collect DART Filings: 18:45 KST
with DAG(
    'collect_dart_filings',
    default_args=default_args,
    schedule_interval='45 18 * * 1-5',
    start_date=datetime(2025, 1, 1, tzinfo=kst),
    catchup=False,
    tags=['data', 'dart', 'filings'],
) as dag_dart:
    run_dart = BashOperator(
        task_id='run_collect_dart_filings',
        bash_command='curl -sf --max-time 300 -X POST http://job-worker:8095/jobs/collect-dart-filings',
    )

# 6. Data Cleanup (Weekly): 03:00 KST on Sunday
# 보관 정책: NEWS_SENTIMENT(30일), STOCK_MINUTE_PRICE(7일), LLM_DECISION_LEDGER(90일) 등
with DAG(
    'data_cleanup_weekly',
    default_args=default_args,
    schedule_interval='0 3 * * 0',
    start_date=datetime(2025, 1, 1, tzinfo=kst),
    catchup=False,
    tags=['maintenance', 'cleanup', 'retention'],
) as dag_cleanup:
    run_cleanup = BashOperator(
        task_id='run_cleanup_old_data',
        bash_command='curl -sf --max-time 600 -X POST http://job-worker:8095/jobs/cleanup-old-data',
    )

# 7. Collect Foreign Holding Ratio: 18:35 KST (investor trading 수집 이후)
# pykrx로 외국인 보유비율(지분율) 수집 → STOCK_INVESTOR_TRADING.FOREIGN_HOLDING_RATIO UPDATE
with DAG(
    'collect_foreign_holding_ratio',
    default_args=default_args,
    schedule_interval='35 18 * * 1-5',
    start_date=datetime(2025, 1, 1, tzinfo=kst),
    catchup=False,
    tags=['data', 'investor', 'foreign', 'holding'],
) as dag_foreign:
    run_foreign = BashOperator(
        task_id='run_collect_foreign_holding_ratio',
        bash_command='curl -sf --max-time 300 -X POST http://job-worker:8095/jobs/collect-foreign-holding',
    )

# 8. Naver Sector Update (Weekly): 20:00 KST on Sunday
# 네이버 업종 분류(79개 세분류) 크롤링 → STOCK_MASTER.SECTOR_NAVER 업데이트
with DAG(
    'update_naver_sectors_weekly',
    default_args={
        **default_args,
        'retries': 2,
        'execution_timeout': timedelta(minutes=15),
    },
    schedule_interval='0 20 * * 0',
    start_date=datetime(2025, 1, 1, tzinfo=kst),
    catchup=False,
    tags=['data', 'sector', 'naver', 'weekly'],
) as dag_naver_sector:
    run_naver_sector = BashOperator(
        task_id='run_update_naver_sectors',
        bash_command='curl -sf --max-time 900 -X POST http://job-worker:8095/jobs/update-naver-sectors',
    )
