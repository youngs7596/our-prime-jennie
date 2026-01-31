"""
services/price-monitor/main.py - 실시간 가격 모니터링 서비스
=========================================================

이 서비스는 보유 종목의 가격을 실시간 모니터링하여 매도 신호를 발생시킵니다. (Redis Streams 기반)

매도 조건:
---------
1. 목표가 도달 (PROFIT_TARGET)
2. 손절가 도달 (STOP_LOSS)
3. RSI 과매수 (RSI > 70/75/78)
4. 보유 기간 초과 (TIME_EXIT)
5. ATR 기반 트레일링 스탑

처리 흐름:
---------
1. Redis Streams(kis:prices) 구독 (from kis-gateway)
2. 실시간 가격 수신 시 보유 종목(PORTFOLIO)과 대조
3. 매도 조건 충족 시 sell-orders 큐로 발행

출력:
----
RabbitMQ sell-orders 큐로 매도 신호 발행

환경변수:
--------
- PORT: HTTP 서버 포트 (기본: 8088)
- TRADING_MODE: REAL/MOCK
- RABBITMQ_URL: RabbitMQ 연결 URL
- KIS_GATEWAY_URL: KIS Gateway URL
- REDIS_URL: Redis 연결 URL
"""

import os
import sys
import logging
import threading
from dotenv import load_dotenv
from flask import Flask, jsonify

# shared 패키지 임포트 경로 설정
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import shared.auth as auth
from shared.kis.client import KISClient as KIS_API
from shared.config import ConfigManager
from shared.rabbitmq import RabbitMQPublisher
from shared.notification import TelegramBot
from shared.graceful_shutdown import GracefulShutdown, init_global_shutdown

from monitor import PriceMonitor

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - [%(funcName)s] - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# 전역 변수
price_monitor = None
monitor_thread = None
is_monitoring = False
rabbitmq_url = None
rabbitmq_sell_queue = None
tasks_publisher = None
monitor_lock = threading.Lock()
shutdown_handler: GracefulShutdown = None


def _on_shutdown_callback():
    """Graceful Shutdown 시 호출되는 콜백"""
    global is_monitoring
    logger.info("🛑 [Graceful Shutdown] price-monitor 종료 콜백 실행...")

    # Price Monitor 정지
    with monitor_lock:
        is_monitoring = False
        if price_monitor:
            try:
                price_monitor.stop_monitoring()
                logger.info("   - PriceMonitor stop_monitoring() 호출")
            except Exception as e:
                logger.warning(f"   - PriceMonitor 정지 오류: {e}")

    logger.info("✅ [Graceful Shutdown] price-monitor 콜백 완료")


def initialize_service():
    """서비스 초기화"""
    global price_monitor, rabbitmq_url, rabbitmq_sell_queue, tasks_publisher, shutdown_handler

    logger.info("=== Price Monitor Service 초기화 시작 (Redis Streams Mode) ===")
    load_dotenv()
    
    try:
        # 1. DB Connection Pool 초기화 (SQLAlchemy 사용)
        from shared.db.connection import ensure_engine_initialized
        logger.info("🔧 DB Connection 초기화 중...")
        ensure_engine_initialized()
        logger.info("✅ DB Connection 초기화 완료")
        
        # 2. KIS API 초기화
        trading_mode = os.getenv("TRADING_MODE", "MOCK")
        logger.info(f"거래 모드: {trading_mode}")
        
        kis = KIS_API(
            app_key=auth.get_secret(os.getenv(f"{trading_mode}_SECRET_ID_APP_KEY")),
            app_secret=auth.get_secret(os.getenv(f"{trading_mode}_SECRET_ID_APP_SECRET")),
            base_url=os.getenv(f"KIS_BASE_URL_{trading_mode}"),
            account_prefix=auth.get_secret(os.getenv(f"{trading_mode}_SECRET_ID_ACCOUNT_PREFIX")),
            account_suffix=os.getenv("KIS_ACCOUNT_SUFFIX"),
            trading_mode=trading_mode
        )
        kis.authenticate()
        logger.info("✅ KIS API 연결 초기화 완료")
        
        # 3. ConfigManager 초기화
        config_manager = ConfigManager(db_conn=None, cache_ttl=300)
        
        # 4. Telegram Bot (가격 알림용, 선택)
        telegram_token = auth.get_secret("telegram_bot_token") if auth.get_secret("telegram_bot_token") else os.getenv("TELEGRAM_BOT_TOKEN")
        telegram_chat_id = auth.get_secret("telegram_chat_id") if auth.get_secret("telegram_chat_id") else os.getenv("TELEGRAM_CHAT_ID")
        telegram_bot = TelegramBot(token=telegram_token, chat_id=telegram_chat_id) if telegram_token and telegram_chat_id else None
        
        # 5. 매도 요청 Publisher 초기화 (RabbitMQ)
        rabbitmq_url = os.getenv("RABBITMQ_URL", "amqp://guest:guest@rabbitmq:5672/")
        rabbitmq_sell_queue = os.getenv("RABBITMQ_QUEUE_SELL_ORDERS", "sell-orders")
        
        tasks_publisher = RabbitMQPublisher(amqp_url=rabbitmq_url, queue_name=rabbitmq_sell_queue)
        logger.info("✅ RabbitMQ Publisher 초기화 완료 (queue=%s)", rabbitmq_sell_queue)
        
        # 6. Price Monitor 초기화
        price_monitor = PriceMonitor(
            kis=kis,
            config=config_manager,
            tasks_publisher=tasks_publisher,
            telegram_bot=telegram_bot
        )
        logger.info("✅ Price Monitor 초기화 완료")

        # 7. Graceful Shutdown Handler 초기화
        shutdown_handler = init_global_shutdown(
            timeout=30,
            on_shutdown=_on_shutdown_callback,
            service_name="price-monitor"
        )
        logger.info("✅ Graceful Shutdown Handler 초기화 완료")

        logger.info("=== Price Monitor Service 초기화 완료 ===")
        # 자동 시작 (환경변수에 따라)
        if os.getenv("AUTO_START_MONITOR", "true").lower() == "true":
            _start_monitor_thread(trigger_source="auto_start")

        return True
        
    except Exception as e:
        logger.critical(f"❌ 초기화 실패: {e}", exc_info=True)
        return False


@app.route('/health', methods=['GET'])
def health_check():
    """Enhanced health check with detailed status"""
    is_ready = price_monitor is not None
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

    # RabbitMQ Publisher 체크
    checks["rabbitmq"] = "ok" if tasks_publisher else "not_initialized"

    # 모니터링 상태
    checks["monitoring_active"] = "ok" if is_monitoring else "stopped"

    # 전체 상태 결정
    if not is_ready:
        status = "initializing"
        http_status = 503
    elif is_shutting_down:
        status = "shutting_down"
        http_status = 503
    elif not is_monitoring:
        status = "degraded"
        http_status = 200
    else:
        status = "healthy"
        http_status = 200

    response = {
        "status": status,
        "service": "price-monitor",
        "is_monitoring": is_monitoring,
        "ready": is_ready and not is_shutting_down,
        "live": is_live,
        "shutting_down": is_shutting_down,
        "checks": checks,
        "in_flight_tasks": shutdown_status.get("in_flight_tasks", 0),
        "uptime_seconds": shutdown_status.get("uptime_seconds", 0)
    }

    return jsonify(response), http_status


@app.route('/start', methods=['POST'])
def start_monitoring():
    try:
        result = _start_monitor_thread(trigger_source="http")
        http_status = 200 if result.get("status") != "error" else 500
        return jsonify(result), http_status
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/stop', methods=['POST'])
def stop_monitoring():
    try:
        result = _stop_monitor_thread(trigger_source="http")
        return jsonify(result), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/', methods=['GET'])
def root():
    return jsonify({
        "service": "price-monitor",
        "version": "v2.0-streams",
        "trading_mode": os.getenv("TRADING_MODE", "MOCK"),
        "dry_run": os.getenv("DRY_RUN", "true"),
        "is_monitoring": is_monitoring
    }), 200


def _start_monitor_thread(trigger_source: str):
    global monitor_thread, is_monitoring
    if not price_monitor:
        raise RuntimeError("Service not initialized")

    with monitor_lock:
        if is_monitoring:
            logger.info("⚠️ Price Monitor 이미 실행 중 (trigger=%s)", trigger_source)
            return {"status": "already_running"}

        price_monitor.stop_event.clear()
        dry_run = os.getenv("DRY_RUN", "true").lower() == "true"
        # Thread Wrapper to ensure state reset on exit
        def _monitor_thread_wrapper(dry_run_arg):
            global is_monitoring, monitor_thread
            try:
                price_monitor.start_monitoring(dry_run=dry_run_arg)
            except Exception as e:
                logger.error(f"❌ Price Monitor 쓰레드 비정상 종료: {e}", exc_info=True)
            finally:
                with monitor_lock:
                    is_monitoring = False
                    monitor_thread = None
                logger.info("ℹ️ Price Monitor 쓰레드 종료 (상태 초기화 완료)")

        monitor_thread = threading.Thread(
            target=_monitor_thread_wrapper,
            args=(dry_run,),
            daemon=True,
        )
        is_monitoring = True
        monitor_thread.start()
        logger.info("🚀 Price Monitor 시작 (trigger=%s, dry_run=%s)", trigger_source, dry_run)
        return {"status": "started", "dry_run": dry_run, "trigger": trigger_source}


def _stop_monitor_thread(trigger_source: str):
    global monitor_thread, is_monitoring
    with monitor_lock:
        if not is_monitoring:
            logger.info("ℹ️ Price Monitor 정지 요청 (이미 중지 상태, trigger=%s)", trigger_source)
            return {"status": "not_running"}

        logger.info("🛑 Price Monitor 정지 요청 수신 (trigger=%s)", trigger_source)
        is_monitoring = False # 플래그 먼저 내림
        if price_monitor:
            price_monitor.stop_monitoring()

        # 쓰레드 join은 락 안에서 하면 데드락 위험이 있으므로 락 밖에서 하거나 가볍게 처리
        # 여기선 join을 생략하거나 짧게 대기.
        # monitor.py의 loop가 stop_event를 체크하므로 자연스럽게 종료됨.
        
        return {"status": "stopped", "trigger": trigger_source}


if price_monitor is None and os.getenv('WERKZEUG_RUN_MAIN') != 'true':
    if not initialize_service():
        logger.critical("서비스 초기화 실패")
        raise RuntimeError("Service initialization failed")

if __name__ == '__main__':
    if price_monitor is None:
        if not initialize_service():
            sys.exit(1)
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port, debug=False)
