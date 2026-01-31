"""
services/buy-scanner/main.py - 매수 신호 스캔 서비스 (Stream-Only)
================================================================

이 서비스는 Watchlist 종목들의 기술적 매수 신호를 실시간으로 스캔합니다.

매수 신호 유형:
-------------
1. RSI 과매도 (RSI < 30)
2. 볼린저밴드 하단 터치
3. 골든크로스 (MA5 > MA20) + Super Prime (Legendary Pattern)

처리 흐름 (Redis Streams / WebSocket):
------------------------------------
1. Hot Watchlist 로드 (Redis) & Foreign Supply Data 로드
2. KIS WebSocket(via kis-gateway)으로 실시간 가격 구독
3. Redis Stream(kis:prices) 소비
4. 매수 신호 발생 시 buy-signals 큐로 발행

환경변수:
--------
- PORT: HTTP 서버 포트 (기본: 8081)
- TRADING_MODE: REAL/MOCK
- RABBITMQ_URL: RabbitMQ 연결 URL
- USE_REDIS_STREAMS: true (필수)
"""

import os
import sys
import uuid
import logging
import threading
import time
from datetime import datetime, timezone
from flask import Flask, request, jsonify
from dotenv import load_dotenv

# shared 패키지 임포트 경로 설정
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import shared.auth as auth
import shared.database as database
import shared.redis_cache as redis_cache
from shared.kis.client import KISClient as KIS_API
from shared.kis.gateway_client import KISGatewayClient
from shared.config import ConfigManager
from shared.rabbitmq import RabbitMQPublisher, RabbitMQWorker
from shared.graceful_shutdown import GracefulShutdown, init_global_shutdown
# from shared.scheduler_runtime import parse_job_message, SchedulerJobMessage # Removed
# from shared.scheduler_client import mark_job_run # Polling 제거로 미사용

from opportunity_watcher import BuyOpportunityWatcher
# from scanner import BuyScanner # scanner.py 삭제됨

# Redis Streams 지원 (WebSocket 공유 아키텍처)
try:
    from shared.kis.stream_consumer import StreamPriceConsumer
    REDIS_STREAMS_AVAILABLE = True
except ImportError:
    REDIS_STREAMS_AVAILABLE = False

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - [%(funcName)s] - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# 전역 변수
rabbitmq_publisher = None
# scheduler_job_worker = None # Removed
# scheduler_job_publisher = None # Removed
# scheduler_job_queue = None # Removed

# WebSocket 모드 전역 변수
kis_client = None  # WebSocket용 KIS 클라이언트
opportunity_watcher = None
websocket_thread = None
is_websocket_mode = False
websocket_lock = threading.Lock()

# Redis Streams 모드 전역 변수
stream_consumer: 'StreamPriceConsumer' = None
use_redis_streams = False

# Graceful Shutdown Handler
shutdown_handler: GracefulShutdown = None


def _on_shutdown_callback():
    """Graceful Shutdown 시 호출되는 콜백"""
    logger.info("🛑 [Graceful Shutdown] buy-scanner 종료 콜백 실행...")

    # 1. BuyOpportunityWatcher stop_event 설정
    if opportunity_watcher:
        opportunity_watcher.stop_event.set()
        logger.info("   - BuyOpportunityWatcher stop_event 설정")

    # 2. Redis Streams Consumer 정지
    if stream_consumer:
        try:
            stream_consumer.stop()
            logger.info("   - Redis Streams Consumer 정지")
        except Exception as e:
            logger.warning(f"   - Redis Streams Consumer 정지 오류: {e}")

    # 3. KIS WebSocket 정지
    if kis_client and hasattr(kis_client, 'websocket'):
        try:
            kis_client.websocket.stop()
            logger.info("   - KIS WebSocket 정지")
        except Exception as e:
            logger.warning(f"   - KIS WebSocket 정지 오류: {e}")

    logger.info("✅ [Graceful Shutdown] buy-scanner 콜백 완료")


def initialize_service():
    """서비스 초기화"""
    global scanner, rabbitmq_publisher, scheduler_job_worker, scheduler_job_publisher, scheduler_job_queue
    global kis_client, opportunity_watcher, is_websocket_mode, shutdown_handler

    logger.info("=== Buy Scanner Service 초기화 시작 ===")
    load_dotenv()
    
    try:
        # 1. DB Connection Pool 초기화 (SQLAlchemy 사용)
        from shared.db.connection import ensure_engine_initialized
        logger.info("🔧 DB Connection 초기화 중...")
        ensure_engine_initialized()
        logger.info("✅ DB Connection 초기화 완료")
        
        # 2. KIS API 초기화
        trading_mode = os.getenv("TRADING_MODE", "MOCK")
        use_gateway = os.getenv("USE_KIS_GATEWAY", "true").lower() == "true"
        is_websocket_mode = os.getenv("USE_WEBSOCKET_MODE", "true").lower() == "true"
        is_mock_websocket = os.getenv("MOCK_SKIP_TIME_CHECK", "false").lower() == "true"
        
        # [수정] WebSocket 모드에서도 Gateway 사용 가능 (Mock 환경)
        # Mock WebSocket 모드: Gateway + Mock SocketIO 서버
        # Real WebSocket 모드: 직접 KIS API 연결 + 실 WebSocket
        if is_websocket_mode and not is_mock_websocket:
            # 실제 KIS WebSocket 사용 시 직접 연결 필요
            kis = KIS_API(
                app_key=auth.get_secret(os.getenv(f"{trading_mode}_SECRET_ID_APP_KEY")),
                app_secret=auth.get_secret(os.getenv(f"{trading_mode}_SECRET_ID_APP_SECRET")),
                base_url=os.getenv(f"KIS_BASE_URL_{trading_mode}"),
                account_prefix=auth.get_secret(os.getenv(f"{trading_mode}_SECRET_ID_ACCOUNT_PREFIX")),
                account_suffix=os.getenv("KIS_ACCOUNT_SUFFIX"),
                token_file_path="/tmp/kis_token_buy_scanner.json",
                trading_mode=trading_mode
            )
            kis.authenticate()
            kis_client = kis  # WebSocket용 저장
            logger.info("✅ KIS API 초기화 완료 (Real WebSocket 모드)")
        else:
            # Gateway 사용 (폴링 모드 또는 Mock WebSocket 모드)
            kis = KISGatewayClient()
            logger.info("✅ KIS Gateway Client 초기화 완료")
        
        # 3. ConfigManager 초기화
        config_manager = ConfigManager(db_conn=None, cache_ttl=300)
        
        # 4. RabbitMQ Publisher 초기화
        amqp_url = os.getenv("RABBITMQ_URL", "amqp://guest:guest@rabbitmq:5672/")
        queue_name = os.getenv("RABBITMQ_QUEUE_BUY_SIGNALS", "buy-signals")
        rabbitmq_publisher = RabbitMQPublisher(amqp_url=amqp_url, queue_name=queue_name)
        logger.info("✅ RabbitMQ Publisher 초기화 완료 (queue=%s)", queue_name)

        # 6. 실시간 모드 결정: Redis Streams vs Direct WebSocket
        use_redis_streams = os.getenv("USE_REDIS_STREAMS", "false").lower() == "true"
        
        if is_websocket_mode:
            redis_url = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
            opportunity_watcher = BuyOpportunityWatcher(
                config=config_manager,
                tasks_publisher=rabbitmq_publisher,
                redis_url=redis_url
            )
            
            if use_redis_streams and REDIS_STREAMS_AVAILABLE:
                # ⭐ Redis Streams 모드: Gateway 통해 공유 WebSocket 사용 (권장)
                logger.info("🔄 Redis Streams 모드 활성화 (kis-gateway 공유 WebSocket)")
                _start_redis_streams_monitoring()
            else:
                # 기존 Direct WebSocket 모드 (Legacy, 테스트용)
                logger.info("✅ BuyOpportunityWatcher 초기화 완료 (Mock WebSocket: %s)", is_mock_websocket)
                _start_websocket_monitoring()
        else:
             logger.warning("⚠️ USE_WEBSOCKET_MODE=false 입니다. buy-scanner는 이제 실시간 전용입니다.")
        
        # 7. Graceful Shutdown Handler 초기화
        shutdown_handler = init_global_shutdown(
            timeout=30,
            on_shutdown=_on_shutdown_callback,
            service_name="buy-scanner"
        )
        logger.info("✅ Graceful Shutdown Handler 초기화 완료")

        logger.info("=== Buy Scanner Service 초기화 완료 ===")
        return True

    except Exception as e:
        logger.critical(f"❌ 초기화 실패: {e}", exc_info=True)
        return False


def _start_redis_streams_monitoring():
    """Redis Streams 기반 실시간 감시 시작 (kis-gateway 공유 WebSocket)"""
    global stream_consumer, websocket_thread
    
    redis_url = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
    gateway_url = os.getenv("KIS_GATEWAY_URL", "http://127.0.0.1:8080")
    
    stream_consumer = StreamPriceConsumer(redis_url=redis_url)
    
    def streams_loop():
        logger.info("=== Redis Streams 매수 신호 감시 시작 ===")
        last_heartbeat_time = 0
        
        while not opportunity_watcher.stop_event.is_set():
            try:
                # Hot Watchlist 로드
                opportunity_watcher.load_hot_watchlist()
                hot_codes = opportunity_watcher.get_watchlist_codes()
                
                if not hot_codes:
                    logger.info("   (Streams) Hot Watchlist 비어있음. 60초 후 다시 확인합니다.")
                    time.sleep(60)
                    continue
                
                logger.info(f"   (Streams) {len(hot_codes)}개 종목 구독 요청 → Gateway...")
                
                # Gateway에 구독 요청 및 Redis Streams 소비 시작
                stream_consumer.start_consuming(
                    on_price_func=_on_stream_price_update,
                    consumer_group="buy-scanner-group",
                    consumer_name=f"buy-scanner-{os.getpid()}",
                    codes_to_subscribe=hot_codes,
                    gateway_url=gateway_url
                )
                
                logger.info("   (Streams) ✅ Redis Streams 소비 시작!")
                
                last_watchlist_check = time.time()
                
                # 감시 루프
                while stream_consumer.is_connected() and not opportunity_watcher.stop_event.is_set():
                    time.sleep(1)
                    now = time.time()
                    
                    # Heartbeat 발행 (5초마다)
                    if now - last_heartbeat_time >= 5:
                        opportunity_watcher.publish_heartbeat()
                        last_heartbeat_time = now
                    
                    # Watchlist 업데이트 체크 (30초마다)
                    if now - last_watchlist_check >= 30:
                        if opportunity_watcher.check_for_update():
                            logger.info("🔄 (Streams) Hot Watchlist 업데이트 감지! 재구독합니다.")
                            # 새 종목만 추가 구독 요청
                            new_codes = opportunity_watcher.get_watchlist_codes()
                            stream_consumer.request_subscription(new_codes, gateway_url)
                        last_watchlist_check = now
                
                if opportunity_watcher.stop_event.is_set():
                    break
                    
                logger.warning("   (Streams) 연결 끊김. 재시작 시도.")
                
            except Exception as e:
                logger.error(f"❌ (Streams) 감시 루프 오류: {e}", exc_info=True)
                time.sleep(60)
        
        stream_consumer.stop()
        logger.info("=== Redis Streams 매수 신호 감시 종료 ===")
    
    websocket_thread = threading.Thread(target=streams_loop, daemon=True)
    websocket_thread.start()


def _on_stream_price_update(stock_code: str, current_price: float, current_high: float):
    """Redis Streams 가격 업데이트 콜백"""
    # [Emergency Stop Check]
    if redis_cache.is_trading_stopped() or redis_cache.is_trading_paused():
        return

    if not opportunity_watcher:
        return
    
    # 매수 신호 체크
    signal = opportunity_watcher.on_price_update(stock_code, current_price, volume=0)
    
    if signal:
        # 매수 신호 발행
        opportunity_watcher.publish_signal(signal)


def _start_websocket_monitoring():
    """WebSocket 기반 실시간 감시 시작"""
    global websocket_thread
    
    is_mock_websocket = os.getenv("MOCK_SKIP_TIME_CHECK", "false").lower() == "true"
    
    def websocket_loop():
        logger.info("=== WebSocket 매수 신호 감시 시작 ===")
        last_heartbeat_time = 0
        
        while not opportunity_watcher.stop_event.is_set():
            try:
                # Hot Watchlist 로드
                opportunity_watcher.load_hot_watchlist()
                hot_codes = opportunity_watcher.get_watchlist_codes()
                
                if not hot_codes:
                    logger.info("   (WS) Hot Watchlist 비어있음. 60초 후 다시 확인합니다.")
                    time.sleep(60)
                    continue
                
                logger.info(f"   (WS) {len(hot_codes)}개 종목 WebSocket 구독 시작...")
                
                if is_mock_websocket:
                    # [Mock 모드] python-socketio로 Mock 서버 연결
                    _start_mock_websocket_loop(hot_codes, last_heartbeat_time)
                else:
                    # [Real 모드] KIS WebSocket 연결
                    if kis_client is None:
                        logger.error("   (WS) ❌ KIS Client가 초기화되지 않았습니다!")
                        time.sleep(60)
                        continue
                    
                    kis_client.websocket.start_realtime_monitoring(
                        portfolio_codes=hot_codes,
                        on_price_func=_on_price_update
                    )
                    
                    if not kis_client.websocket.connection_event.wait(timeout=15):
                        logger.error("   (WS) ❌ WebSocket 연결 타임아웃! 재시도합니다.")
                        time.sleep(5)
                        continue
                    
                    logger.info("   (WS) ✅ WebSocket 연결 성공! 실시간 감시 중.")
                    
                    last_watchlist_check = time.time()
                    
                    # 연결 유지 루프
                    while kis_client.websocket.connection_event.is_set() and not opportunity_watcher.stop_event.is_set():
                        time.sleep(1)
                        now = time.time()
                        
                        # Heartbeat 발행 (5초마다)
                        if now - last_heartbeat_time >= 5:
                            opportunity_watcher.publish_heartbeat()
                            last_heartbeat_time = now
                            
                        # Watchlist 업데이트 체크 (30초마다)
                        if now - last_watchlist_check >= 30:
                            if opportunity_watcher.check_for_update():
                                logger.info("🔄 (WS) Hot Watchlist 업데이트 감지! 재연결을 진행합니다.")
                                kis_client.websocket.stop() # 이로 인해 connection_event가 clear되어 루프 종료
                                break
                            last_watchlist_check = now
                    
                    if opportunity_watcher.stop_event.is_set():
                        break
                    
                    logger.warning("   (WS) WebSocket 연결 끊김. 재연결 시도.")
                
            except Exception as e:
                logger.error(f"❌ (WS) 감시 루프 오류: {e}", exc_info=True)
                time.sleep(60)
        
        if not is_mock_websocket and kis_client:
            kis_client.websocket.stop()
        logger.info("=== WebSocket 매수 신호 감시 종료 ===")
    
    websocket_thread = threading.Thread(target=websocket_loop, daemon=True)
    websocket_thread.start()


def _start_mock_websocket_loop(hot_codes: list, last_heartbeat_time: float):
    """Mock WebSocket 서버 연결 및 가격 수신 루프"""
    try:
        import socketio
    except ImportError:
        logger.error("❌ (Mock WS) python-socketio 라이브러리가 설치되지 않았습니다!")
        return
    
    mock_ws_url = os.getenv('KIS_BASE_URL_MOCK', 'http://localhost:9443')
    logger.info(f"   (Mock WS) Mock 서버 연결 시도: {mock_ws_url}")
    
    sio = socketio.Client(logger=False, engineio_logger=False)
    connection_event = threading.Event()
    price_update_count = 0  # 가격 업데이트 카운터
    
    @sio.event
    def connect():
        logger.info("   (Mock WS) ✅ SocketIO 연결 성공!")
        connection_event.set()
        # 종목 구독 요청
        sio.emit('subscribe', {'codes': hot_codes})
    
    @sio.on('connected')
    def on_connected(data):
        logger.info(f"   (Mock WS) 서버 환영 메시지: {data.get('message', '')}")
    
    @sio.on('subscribed')
    def on_subscribed(data):
        logger.info(f"   (Mock WS) ✅ 구독 완료: {data.get('total', 0)}개 종목")
    
    @sio.on('price_update')
    def on_price_update(data):
        # [Emergency Stop Check]
        if redis_cache.is_trading_stopped() or redis_cache.is_trading_paused():
            return

        nonlocal price_update_count
        price_update_count += 1
        
        stock_code = data.get('stock_code')
        current_price = float(data.get('current_price', 0))
        
        # 로그 출력 (처음 5회 + 이후 10회마다 1회)
        if price_update_count <= 5 or price_update_count % 10 == 0:
            logger.info(f"   (Mock WS) 💰 가격 #{price_update_count}: {stock_code} = {current_price:,.0f}원")
        
        if stock_code and current_price > 0:
            # BuyOpportunityWatcher에 가격 업데이트 전달
            signal = opportunity_watcher.on_price_update(stock_code, current_price, volume=0)
            if signal:
                logger.info(f"   (Mock WS) 🎯 매수 신호 발생! {stock_code}")
                opportunity_watcher.publish_signal(signal)
    
    @sio.on('buy_signal')
    def on_buy_signal(data):
        """테스트 API에서 발행된 매수 신호 직접 수신"""
        # [Emergency Stop Check]
        if redis_cache.is_trading_stopped() or redis_cache.is_trading_paused():
            return

        stock_code = data.get('stock_code')
        signal_type = data.get('signal_type', 'TEST')
        
        logger.info(f"   (Mock WS) 🎯 테스트 매수 신호 수신: {stock_code} ({signal_type})")
        
        # RabbitMQ로 즉시 발행
        if opportunity_watcher and opportunity_watcher.tasks_publisher:
            opportunity_watcher.tasks_publisher.publish(data)
            logger.info(f"   (Mock WS) ✅ RabbitMQ 발행 완료: {stock_code}")
    
    @sio.event
    def disconnect():
        logger.warning("   (Mock WS) ⚠️ 연결 해제됨")
        connection_event.clear()
    
    try:
        sio.connect(mock_ws_url, wait_timeout=10)
        
        if connection_event.wait(timeout=10):
            logger.info("   (Mock WS) ✅ 실시간 감시 시작!")
            
            last_watchlist_check = time.time()
            
            # 연결 유지 루프
            while connection_event.is_set() and not opportunity_watcher.stop_event.is_set():
                time.sleep(1)
                now = time.time()
                # Heartbeat 발행 (5초마다)
                if now - last_heartbeat_time >= 5:
                    opportunity_watcher.publish_heartbeat()
                    last_heartbeat_time = now
                    
                # Watchlist 업데이트 체크 (30초마다)
                if now - last_watchlist_check >= 30:
                    if opportunity_watcher.check_for_update():
                        logger.info("🔄 (Mock WS) Hot Watchlist 업데이트 감지! 재연결을 진행합니다.")
                        sio.disconnect()
                        break
                    last_watchlist_check = now
        else:
            logger.error("   (Mock WS) ❌ 연결 타임아웃!")
    except Exception as e:
        logger.error(f"   (Mock WS) ❌ 연결 오류: {e}")
    finally:
        try:
            sio.disconnect()
        except:
            pass


def _on_price_update(stock_code: str, current_price: float, current_high: float):
    """WebSocket 가격 업데이트 콜백"""
    # [Emergency Stop Check]
    if redis_cache.is_trading_stopped() or redis_cache.is_trading_paused():
        return

    if not opportunity_watcher:
        return
    
    # 매수 신호 체크
    signal = opportunity_watcher.on_price_update(stock_code, current_price, volume=0)
    
    if signal:
        # 매수 신호 발행
        opportunity_watcher.publish_signal(signal)


@app.route('/health', methods=['GET'])
def health_check():
    """Enhanced health check with detailed status"""
    # 기본 상태 확인
    is_ready = opportunity_watcher is not None and rabbitmq_publisher is not None
    is_live = True  # 프로세스 살아있음

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

    # Redis 체크
    try:
        if opportunity_watcher and opportunity_watcher.redis:
            opportunity_watcher.redis.ping()
            checks["redis"] = "ok"
        else:
            checks["redis"] = "not_initialized"
    except Exception as e:
        checks["redis"] = f"error: {str(e)[:50]}"

    # RabbitMQ 체크
    checks["rabbitmq"] = "ok" if rabbitmq_publisher else "not_initialized"

    # 전체 상태 결정
    if not is_ready:
        status = "initializing"
        http_status = 503
    elif is_shutting_down:
        status = "shutting_down"
        http_status = 503  # 종료 중에는 새 트래픽 받지 않음
    elif checks.get("redis") != "ok":
        status = "degraded"
        http_status = 200
    else:
        status = "healthy"
        http_status = 200

    response = {
        "status": status,
        "service": "buy-scanner",
        "mode": "realtime-stream",
        "ready": is_ready and not is_shutting_down,
        "live": is_live,
        "shutting_down": is_shutting_down,
        "checks": checks,
        "in_flight_tasks": shutdown_status.get("in_flight_tasks", 0),
        "uptime_seconds": shutdown_status.get("uptime_seconds", 0)
    }

    return jsonify(response), http_status





@app.route('/', methods=['GET'])
def root():
    return jsonify({
        "service": "buy-scanner",
        "version": "v1.0",
        "trading_mode": os.getenv("TRADING_MODE", "MOCK"),
        "dry_run": os.getenv("DRY_RUN", "true")
    }), 200


if opportunity_watcher is None and os.getenv('WERKZEUG_RUN_MAIN') != 'true':
    logger.info("모듈 로드 시 서비스 초기화 시작")
    if not initialize_service():
        logger.critical("서비스 초기화 실패")
        raise RuntimeError("Service initialization failed")

if __name__ == '__main__':
    if opportunity_watcher is None:
        if not initialize_service():
            sys.exit(1)
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port, debug=False)
