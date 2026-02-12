"""
services/buy-executor/main.py - 매수 실행 서비스
===============================================

이 서비스는 매수 신호를 받아 실제 주문을 실행합니다.

주요 기능:
---------
1. Redis Streams에서 매수 신호 수신 (stream:buy-signals)
2. LLM 점수 확인 및 포지션 사이징
3. KIS Gateway를 통한 매수 주문 실행
4. 텔레그램 알림 발송
5. 거래 로그 기록 (TRADELOG)

입력 (Redis Stream 메시지):
--------------------
{
    "stock_code": "005930",
    "stock_name": "삼성전자",
    "signal_type": "RSI_OVERSOLD",
    "llm_score": 75,
    "price": 70000
}

환경변수:
--------
- PORT: HTTP 서버 포트 (기본: 8082)
- TRADING_MODE: REAL/MOCK
- DRY_RUN: true면 실제 주문 미실행
- MIN_LLM_SCORE: 매수 최소 점수 (Real: 70, Mock: 50)
- REDIS_URL: Redis 연결 URL
- KIS_GATEWAY_URL: KIS Gateway URL
"""

import os
import sys
import logging
import json
import base64
from flask import Flask, request, jsonify
from dotenv import load_dotenv

# shared 패키지 임포트 경로 설정
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import shared.auth as auth
import shared.database as database
from shared.kis.client import KISClient as KIS_API
from shared.kis.gateway_client import KISGatewayClient
from shared.config import ConfigManager
from shared.messaging.trading_signals import TradingSignalWorker, STREAM_BUY_SIGNALS, GROUP_BUY_EXECUTOR
from shared.graceful_shutdown import GracefulShutdown, TaskTracker, init_global_shutdown

# Lazy import: executor 모듈은 사용 시점에 import
# from executor import BuyExecutor

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - [%(funcName)s] - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# 전역 변수
executor = None
stream_worker = None
shutdown_handler: GracefulShutdown = None
task_tracker: TaskTracker = None


def _process_buy_signal(scan_result, source="stream"):
    """매수 신호 처리 로직 (HTTP/Redis Stream 공통 사용)"""
    if not executor:
        raise RuntimeError("Service not initialized")

    # Graceful Shutdown 체크: 종료 중이면 새 작업 거부
    if shutdown_handler and shutdown_handler.is_shutting_down():
        logger.warning("🛑 [Graceful Shutdown] 종료 중이므로 매수 신호 처리 건너뜀")
        return {"status": "skipped", "reason": "service_shutting_down"}

    dry_run = os.getenv('DRY_RUN', 'true').lower() == 'true'
    if dry_run:
        logger.info("🔧 DRY_RUN 모드: 실제 주문은 실행되지 않습니다")

    logger.info(f"[{source.upper()}] 매수 신호 수신: {len(scan_result.get('candidates', []))}개 후보")

    # 작업 추적 (in_flight_tasks 증가)
    if task_tracker:
        with task_tracker.track():
            result = executor.process_buy_signal(scan_result, dry_run=dry_run)
    else:
        result = executor.process_buy_signal(scan_result, dry_run=dry_run)

    if result['status'] == 'success':
        logger.info(f"✅ 매수 처리 완료: {result.get('stock_name', 'N/A')}")
    else:
        logger.warning(f"⚠️ 매수 처리 실패 또는 건너뜀: {result.get('reason', 'Unknown')}")

    return result

def _stream_handler(payload):
    try:
        _process_buy_signal(payload, source="stream")
    except Exception as exc:
        logger.error(f"Stream 메시지 처리 실패: {exc}", exc_info=True)

def _start_stream_worker_if_needed():
    global stream_worker
    if stream_worker and stream_worker._thread and stream_worker._thread.is_alive():
        return

    redis_url = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
    stream_worker = TradingSignalWorker(
        redis_url=redis_url,
        stream_name=STREAM_BUY_SIGNALS,
        group_name=GROUP_BUY_EXECUTOR,
        consumer_name=f"buy-executor-{os.getpid()}",
        handler=_stream_handler,
    )
    stream_worker.start()


def _on_shutdown_callback():
    """Graceful Shutdown 시 호출되는 콜백"""
    logger.info("🛑 [Graceful Shutdown] buy-executor 종료 콜백 실행...")

    # Stream Worker 정지
    if stream_worker:
        try:
            stream_worker.stop()
            logger.info("   - Stream Worker 정지 요청")
        except Exception as e:
            logger.warning(f"   - Stream Worker 정지 오류: {e}")

    logger.info("✅ [Graceful Shutdown] buy-executor 콜백 완료")


def initialize_service():
    """서비스 초기화"""
    global executor, shutdown_handler, task_tracker

    logger.info("=== Buy Executor Service 초기화 시작 ===")
    load_dotenv()
    
    try:
        # Lazy import: BuyExecutor는 초기화 시점에 import
        from executor import BuyExecutor
        
        # 1. DB Connection Pool 초기화 (SQLAlchemy 사용)
        from shared.db.connection import ensure_engine_initialized
        logger.info("🔧 DB Connection 초기화 중...")
        ensure_engine_initialized()
        logger.info("✅ DB Connection 초기화 완료")
        
        # 2. KIS API 초기화
        trading_mode = os.getenv("TRADING_MODE", "MOCK")
        use_gateway = os.getenv("USE_KIS_GATEWAY", "true").lower() == "true"
        logger.info(f"거래 모드: {trading_mode}, Gateway 사용: {use_gateway}")
        
        if use_gateway:
            kis = KISGatewayClient()
            logger.info("✅ KIS Gateway Client 초기화 완료")
        else:
            kis = KIS_API(
                app_key=auth.get_secret(os.getenv(f"{trading_mode}_SECRET_ID_APP_KEY")),
                app_secret=auth.get_secret(os.getenv(f"{trading_mode}_SECRET_ID_APP_SECRET")),
                base_url=os.getenv(f"KIS_BASE_URL_{trading_mode}"),
                account_prefix=auth.get_secret(os.getenv(f"{trading_mode}_SECRET_ID_ACCOUNT_PREFIX")),
                account_suffix=os.getenv("KIS_ACCOUNT_SUFFIX"),
                token_file_path="/tmp/kis_token_buy_executor.json",
                trading_mode=trading_mode
            )
            kis.authenticate()
            logger.info("✅ KIS API 초기화 완료")
        
        # 3. ConfigManager 초기화
        config_manager = ConfigManager(db_conn=None, cache_ttl=300)
        logger.info("✅ ConfigManager 초기화 완료")
        
        # 4. Telegram Bot 초기화
        try:
            telegram_token = auth.get_secret("telegram_bot_token")
            telegram_chat_id = auth.get_secret("telegram_chat_id")
        except Exception:
            logger.warning("텔레그램 Secret 로드 실패, 환경변수 사용")
            telegram_token = os.getenv("TELEGRAM_BOT_TOKEN")
            telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID")
        
        from shared.notification import TelegramBot
        telegram_bot = TelegramBot(token=telegram_token, chat_id=telegram_chat_id)
        logger.info("✅ Telegram Bot 초기화 완료")

        # 5. Buy Executor 초기화
        executor = BuyExecutor(
            kis=kis,
            config=config_manager,
            telegram_bot=telegram_bot
        )
        logger.info("✅ Buy Executor 초기화 완료")

        # 6. Graceful Shutdown Handler 초기화
        shutdown_handler = init_global_shutdown(
            timeout=30,
            on_shutdown=_on_shutdown_callback,
            service_name="buy-executor"
        )
        task_tracker = TaskTracker(shutdown_handler)
        logger.info("✅ Graceful Shutdown Handler 초기화 완료")

        logger.info("=== Buy Executor Service 초기화 완료 ===")

        # Stream 워커 시작
        _start_stream_worker_if_needed()

        return True
        
    except Exception as e:
        logger.critical(f"❌ 초기화 실패: {e}", exc_info=True)
        return False


@app.route('/health', methods=['GET'])
def health_check():
    """Enhanced health check with detailed status"""
    is_ready = executor is not None
    is_live = True

    # Graceful Shutdown 상태
    shutdown_status = {}
    if shutdown_handler:
        shutdown_status = shutdown_handler.get_health_status()
        is_shutting_down = shutdown_status.get("shutting_down", False)
    else:
        is_shutting_down = False
        shutdown_status = {"shutting_down": False, "in_flight_tasks": 0, "uptime_seconds": 0}

    # 의존성 체크
    checks = {}

    # Stream Worker 체크
    if stream_worker and stream_worker._thread and stream_worker._thread.is_alive():
        checks["stream_worker"] = "ok"
    elif stream_worker:
        checks["stream_worker"] = "worker_stopped"
    else:
        checks["stream_worker"] = "not_initialized"

    # 전체 상태 결정
    if not is_ready:
        status = "initializing"
        http_status = 503
    elif is_shutting_down:
        status = "shutting_down"
        http_status = 503
    elif checks.get("stream_worker") != "ok":
        status = "degraded"
        http_status = 200
    else:
        status = "healthy"
        http_status = 200

    response = {
        "status": status,
        "service": "buy-executor",
        "ready": is_ready and not is_shutting_down,
        "live": is_live,
        "shutting_down": is_shutting_down,
        "checks": checks,
        "in_flight_tasks": shutdown_status.get("in_flight_tasks", 0),
        "uptime_seconds": shutdown_status.get("uptime_seconds", 0)
    }

    return jsonify(response), http_status


@app.route('/process', methods=['POST'])
def process():
    """
    Pub/Sub Push 구독 엔드포인트 (Legacy 지원)
    Legacy 엔드포인트, 테스트용으로 유지
    """
    try:
        if not executor:
            return jsonify({"error": "Service not initialized"}), 503
        
        # 1. Pub/Sub 메시지 파싱
        envelope = request.get_json()
        if not envelope:
            return jsonify({"error": "Invalid message"}), 400
        
        pubsub_message = envelope.get('message', {})
        if not pubsub_message:
            return jsonify({"error": "No message"}), 400
        
        message_data = pubsub_message.get('data', '')
        if not message_data:
            return jsonify({"error": "No data"}), 400
        
        try:
            decoded_data = base64.b64decode(message_data).decode('utf-8')
            scan_result = json.loads(decoded_data)
        except Exception as e:
            logger.error(f"Failed to decode message: {e}")
            return jsonify({"error": "Invalid message format"}), 400
        
        # 2. 매수 실행
        result = _process_buy_signal(scan_result, source="http_push")
        
        if result['status'] == 'success':
            return jsonify(result), 200
        else:
            return jsonify(result), 200
        
    except Exception as e:
        logger.error(f"❌ /process 처리 중 오류: {e}", exc_info=True)
        return jsonify({"status": "error", "error": str(e)}), 200


@app.route('/', methods=['GET'])
def root():
    return jsonify({
        "service": "buy-executor",
        "version": "v1.0",
        "trading_mode": os.getenv("TRADING_MODE", "MOCK"),
        "dry_run": os.getenv("DRY_RUN", "true")
    }), 200


if executor is None:
    logger.info("모듈 로드 시 서비스 초기화 시작")
    if not initialize_service():
        logger.critical("서비스 초기화 실패")
        raise RuntimeError("Service initialization failed")

if __name__ == '__main__':
    if executor is None:
        if not initialize_service():
            sys.exit(1)
    else:
        _start_stream_worker_if_needed()
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port, debug=False)
