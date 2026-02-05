"""
Macro Council DAG - 3현자 매크로 분석

매일 07:30 KST에 @hedgecat0301 채널의 장 시작 전 브리핑을 분석하여
일일 매크로 인사이트를 생성합니다.

Enhanced Macro Collection DAG와 연동하여 글로벌 데이터도 통합 분석합니다.

분석 결과:
- DB: DAILY_MACRO_INSIGHT 테이블에 저장 (백테스트용)
- Redis: macro:daily_insight 키에 캐싱 (실시간 서비스용)

비용: ~$0.20/일 (3현자 Council API 비용)
"""

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

# Environment Variables
COMMON_ENV = {
    'PYTHONPATH': '/opt/airflow',
    'MARIADB_HOST': 'mariadb',
    'MARIADB_PORT': '3306',
    'MARIADB_USER': 'jennie',
    'MARIADB_PASSWORD': 'q1w2e3R$',
    'MARIADB_DBNAME': 'jennie_db',
    'REDIS_HOST': 'redis',
    'REDIS_PORT': '6379',
    'TZ': 'Asia/Seoul',
}

# Macro Council: 07:30 KST (Mon-Fri)
# 장 시작 전 브리핑 분석으로 일일 매크로 인사이트 생성
with DAG(
    'macro_council',
    default_args=default_args,
    description='3현자 Council 매크로 분석 (07:30 KST)',
    schedule_interval='30 7 * * 1-5',  # 07:30 KST, Mon-Fri
    start_date=datetime(2025, 1, 1, tzinfo=kst),
    catchup=False,
    tags=['macro', 'council', 'llm', 'analysis'],
) as dag:

    # run_macro_council.py 스크립트가 글로벌 스냅샷 유무를 자체 처리
    # - 글로벌 스냅샷 있으면 함께 분석
    # - 없으면 텔레그램 브리핑만으로 분석
    # - 둘 다 없으면 실패
    run_macro_council = BashOperator(
        task_id='run_macro_council',
        bash_command='python scripts/run_macro_council.py',
        cwd='/opt/airflow',
        env=COMMON_ENV,
        append_env=True,
        execution_timeout=timedelta(minutes=10),  # Council 분석 ~2분 예상
    )
