import os
import requests
import json
import logging
from datetime import datetime, timedelta
# from airflow.models import Variable # Not used yet

# Logger setup
logger = logging.getLogger("airflow.task")

def get_telegram_config():
    """Secrets에서 Telegram 설정 로드"""
    try:
        # Docker Volume으로 마운트된 secrets.json 읽기
        with open("/opt/airflow/secrets.json", "r") as f:
            secrets = json.load(f)
            return secrets.get("TELEGRAM_BOT_TOKEN"), secrets.get("TELEGRAM_CHAT_ID")
    except Exception as e:
        logger.error(f"❌ Failed to load secrets: {e}")
        return None, None

def send_telegram_alert(context):
    """
    Airflow Task 실패 시 호출되는 콜백 함수.
    간단한 알림을 보내고, LLM 분석을 트리거합니다.
    """
    token, chat_id = get_telegram_config()
    if not token or not chat_id:
        logger.error("❌ Telegram Token/ChatID not found.")
        return

    dag_id = context.get('task_instance').dag_id
    task_id = context.get('task_instance').task_id
    execution_date = context.get('execution_date')
    log_url = context.get('task_instance').log_url
    exception = context.get('exception')

    # 1. 즉시 알림 메시지 전송
    message = (
        f"🚨 **Job Failed**\n"
        f"• **DAG**: `{dag_id}`\n"
        f"• **Task**: `{task_id}`\n"
        f"• **Time**: `{execution_date}`\n"
        f"• **Error**: `{str(exception)[:100]}...`\n"
        f"[View Log]({log_url})"
    )
    
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown"
    }
    
    try:
        requests.post(url, json=payload, timeout=5)
        logger.info("✅ Telegram alert sent.")
    except Exception as e:
        logger.error(f"❌ Failed to send Telegram alert: {e}")

    # 2. LLM 분석 요청 (비동기 트리거 또는 직접 호출)
    try:
        analyze_failure_with_llm(context, token, chat_id)
    except Exception as e:
        logger.error(f"⚠️ LLM Analysis skipped due to error: {e}")

def analyze_failure_with_llm(context, token, chat_id):
    """
    실패한 태스크의 로그를 읽어 LLM(Junho)에게 분석을 요청하고 결과를 전송합니다.
    """
    ti = context.get('task_instance')
    # Airflow 2.x 기본 로그 경로 구조: dag_id/task_id/run_id/attempt.log
    # 하지만 Docker Compose 볼륨 매핑에 따라 다를 수 있음.
    # 여기서는 try-catch로 유연하게 처리
    
    # 50줄의 로그를 수집하기 위한 시도
    # 실제 프로덕션에서는 Airflow Task Handler를 통해 읽는 것이 정확하나, 로컬 파일 접근으로 시도
    log_dir = f"/opt/airflow/logs/airflow/dag_id={ti.dag_id}/run_id={ti.run_id}/task_id={ti.task_id}/attempt={ti.try_number}.log"
    # Note: run_id에는 user input이 포함될 수 있어 safe하게 처리해야 하나 내부 시스템이므로 패스
    
    # 만약 파일이 없다면 포기 확인 메시지
    # logger.info(f"Checking log at: {log_dir}")
    
    # Mocking log reading for now if file logic is complex in container
    last_logs = f"Error details for {ti.task_id} in {ti.dag_id}. Exception: {context.get('exception')}"

    # Ollama Gateway 호출 (컨테이너 간 통신: host.docker.internal or service name)
    # my-prime-jennie-ollama-gateway-1 서비스가 ollama-gateway 이름으로 네트워크에 있음
    gateway_url = "http://ollama-gateway:11500/api/generate" 
    
    prompt = (
        f"다음은 Airflow 작업 실패 로그 요약입니다.\n"
        f"에러 원인을 분석하고, 이것이 '일시적 인프라 오류(네트워크 등)'인지 '코드 버그'인지 판단하세요.\n"
        f"해결책을 한 문장으로 제안해주세요.\n\n"
        f"Log Summary:\n{last_logs}"
    )

    payload = {
        "model": "junho", # 없으면 default 모델 사용
        "prompt": prompt,
        "stream": False
    }

    try:
        # Gateway 호출
        res = requests.post(gateway_url, json=payload, timeout=10)
        res.raise_for_status()
        analysis = res.json().get('response', 'No response')
        
        # 분석 결과 전송
        analysis_msg = f"🤖 **Junho's Insight**:\n{analysis}"
        requests.post(f"https://api.telegram.org/bot{token}/sendMessage", json={
            "chat_id": chat_id,
            "text": analysis_msg,
            "parse_mode": "Markdown"
        })
    except Exception as e:
        logger.error(f"Failed to call Ollama: {e}")
