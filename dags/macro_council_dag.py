"""
Macro Council DAG - 3현자 매크로 분석

매일 07:50, 11:50 KST에 @hedgecat0301 채널의 장 시작 전 브리핑을 분석하여
일일 매크로 인사이트를 생성합니다.

Enhanced Macro Collection DAG (07:40, 11:40)와 연동하여 글로벌 데이터도 통합 분석합니다.

분석 결과:
- DB: DAILY_MACRO_INSIGHT 테이블에 저장 (백테스트용)
- Redis: macro:daily_insight 키에 캐싱 (실시간 서비스용)

비용: ~$0.40/일 (3현자 Council API 비용, 하루 2회)
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

# Macro Council: 07:50, 11:50 KST (Mon-Fri)
# enhanced_macro_collection (07:40, 11:40) 수집 완료 후 10분 뒤 분석
with DAG(
    'macro_council',
    default_args=default_args,
    description='3현자 Council 매크로 분석 (07:50, 11:50 KST)',
    schedule_interval='50 7,11 * * 1-5',  # 07:50, 11:50 KST, Mon-Fri
    start_date=datetime(2025, 1, 1, tzinfo=kst),
    catchup=False,
    tags=['macro', 'council', 'llm', 'analysis'],
) as dag:

    run_macro_council = BashOperator(
        task_id='run_macro_council',
        bash_command='curl -sf --max-time 600 -X POST http://job-worker:8095/jobs/macro-council',
        execution_timeout=timedelta(minutes=10),
    )
