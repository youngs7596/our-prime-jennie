"""
Enhanced Macro Collection DAG - 글로벌 매크로 데이터 수집

매일 07:00, 12:00, 18:00 KST에 글로벌 매크로 데이터를 수집합니다.

데이터 소스:
- Finnhub: 글로벌 시장, 경제 캘린더
- FRED: 미국 경제 지표
- BOK ECOS: 한국은행 데이터
- pykrx: KOSPI/KOSDAQ 시세
- RSS: 한국 경제뉴스

결과:
- DB: ENHANCED_MACRO_SNAPSHOT 테이블
- Redis: macro:data:snapshot 키
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
    'retries': 2,
    'retry_delay': timedelta(minutes=5),
    'on_failure_callback': send_telegram_alert,
}

# Environment Variables
COMMON_ENV = {
    'PYTHONPATH': '/opt/airflow',
    'MARIADB_HOST': 'mariadb',
    'MARIADB_PORT': '3306',
    'REDIS_HOST': 'redis',
    'REDIS_PORT': '6379',
    'TZ': 'Asia/Seoul',
}

# Enhanced Macro Collection: 07:00, 12:00, 18:00 KST (Mon-Fri)
with DAG(
    'enhanced_macro_collection',
    default_args=default_args,
    description='글로벌 매크로 데이터 수집 (07:00, 12:00, 18:00 KST)',
    schedule_interval='0 7,12,18 * * 1-5',  # 07:00, 12:00, 18:00 KST, Mon-Fri
    start_date=datetime(2026, 2, 1, tzinfo=kst),
    catchup=False,
    tags=['macro', 'data', 'collection', 'global'],
) as dag:

    # 글로벌 데이터 수집 (Finnhub, FRED)
    collect_global = BashOperator(
        task_id='collect_global_data',
        bash_command='python scripts/collect_enhanced_macro.py --sources finnhub,fred',
        cwd='/opt/airflow',
        env=COMMON_ENV,
        append_env=True,
        execution_timeout=timedelta(minutes=5),
    )

    # 한국 데이터 수집 (BOK, pykrx, RSS)
    # 12:00 실행 시 pykrx 스킵 (11:30 enhanced_macro_quick이 이미 수집)
    collect_korea = BashOperator(
        task_id='collect_korea_data',
        bash_command='HOUR=$(date +%H); if [ "$HOUR" = "12" ]; then python scripts/collect_enhanced_macro.py --sources bok_ecos,rss; else python scripts/collect_enhanced_macro.py --sources bok_ecos,pykrx,rss; fi',
        cwd='/opt/airflow',
        env=COMMON_ENV,
        append_env=True,
        execution_timeout=timedelta(minutes=5),
    )

    # 데이터 통합 및 검증
    validate_and_store = BashOperator(
        task_id='validate_and_store',
        bash_command='python scripts/collect_enhanced_macro.py',
        cwd='/opt/airflow',
        env=COMMON_ENV,
        append_env=True,
        execution_timeout=timedelta(minutes=3),
    )

    # 의존성: 글로벌 + 한국 → 통합
    [collect_global, collect_korea] >> validate_and_store


# Quick Collection: 장중 빠른 업데이트 (pykrx만)
with DAG(
    'enhanced_macro_quick',
    default_args=default_args,
    description='장중 빠른 매크로 업데이트 (pykrx)',
    schedule_interval='30 9-14 * * 1-5',  # 09:30-14:30 KST, 매시간
    start_date=datetime(2026, 2, 1, tzinfo=kst),
    catchup=False,
    tags=['macro', 'data', 'quick'],
) as dag_quick:

    quick_collect = BashOperator(
        task_id='quick_collect',
        bash_command='python scripts/collect_enhanced_macro.py --quick',
        cwd='/opt/airflow',
        env=COMMON_ENV,
        append_env=True,
        execution_timeout=timedelta(minutes=2),
    )
