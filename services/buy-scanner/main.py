"""
services/buy-scanner/main.py - 매수 신호 스캔 서비스
=================================================

이 서비스는 Watchlist 종목들의 기술적 매수 신호를 스캔합니다.

매수 신호 유형:
-------------
1. RSI 과매도 (RSI < 30)
2. 볼린저밴드 하단 터치
3. 20일 저항선 돌파
4. 골든크로스 (MA5 > MA20)

처리 흐름 (WebSocket 모드):
-------------------------
1. Hot Watchlist 로드 (scout-job이 저장한 것)
2. KIS WebSocket으로 실시간 가격 구독
3. 매수 신호 발생 시 buy-signals 큐로 발행

환경변수:
--------
- PORT: HTTP 서버 포트 (기본: 8081)
- TRADING_MODE: REAL/MOCK
- RABBITMQ_URL: RabbitMQ 연결 URL
- USE_WEBSOCKET_MODE: true/false (WebSocket 상시 실행 모드)
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
from shared.scheduler_runtime import parse_job_message, SchedulerJobMessage
from shared.scheduler_client import mark_job_run

from scanner import BuyScanner
from opportunity_watcher import BuyOpportunityWatcher

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - [%(funcName)s] - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# 전역 변수
scanner = None
rabbitmq_publisher = None
scheduler_job_worker = None
scheduler_job_publisher = None
scheduler_job_queue = None

# WebSocket 모드 전역 변수
kis_client = None  # WebSocket용 KIS 클라이언트
opportunity_watcher = None
websocket_thread = None
is_websocket_mode = False
websocket_lock = threading.Lock()


def initialize_service():
    """서비스 초기화"""
    global scanner, rabbitmq_publisher, scheduler_job_worker, scheduler_job_publisher, scheduler_job_queue
    global kis_client, opportunity_watcher, is_websocket_mode
    
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
        
        # 4. Buy Scanner 초기화 (폴백용)
        scanner = BuyScanner(kis=kis, config=config_manager)
        logger.info("✅ Buy Scanner 초기화 완료")
        
        # 5. RabbitMQ Publisher 초기화
        amqp_url = os.getenv("RABBITMQ_URL", "amqp://guest:guest@rabbitmq:5672/")
        queue_name = os.getenv("RABBITMQ_QUEUE_BUY_SIGNALS", "buy-signals")
        rabbitmq_publisher = RabbitMQPublisher(amqp_url=amqp_url, queue_name=queue_name)
        logger.info("✅ RabbitMQ Publisher 초기화 완료 (queue=%s)", queue_name)

        # 6. WebSocket 모드: BuyOpportunityWatcher 초기화
        if is_websocket_mode:
            redis_url = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
            opportunity_watcher = BuyOpportunityWatcher(
                config=config_manager,
                tasks_publisher=rabbitmq_publisher,
                redis_url=redis_url
            )
            logger.info("✅ BuyOpportunityWatcher 초기화 완료 (Mock WebSocket: %s)", is_mock_websocket)
            
            # WebSocket 감시 시작
            _start_websocket_monitoring()
        else:
            # 7. Scheduler Job Worker (폴링 모드)
            if os.getenv("ENABLE_BUY_SCANNER_JOB_WORKER", "true").lower() == "true":
                scheduler_job_queue = os.getenv("SCHEDULER_QUEUE_BUY_SCANNER", "real.jobs.buy-scanner")
                scheduler_job_publisher = RabbitMQPublisher(amqp_url=amqp_url, queue_name=scheduler_job_queue)
                scheduler_job_worker = RabbitMQWorker(
                    amqp_url=amqp_url,
                    queue_name=scheduler_job_queue,
                    handler=handle_scheduler_job_message,
                )
                scheduler_job_worker.start()
                logger.info("✅ Scheduler Job Worker 시작 (queue=%s)", scheduler_job_queue)
                _bootstrap_scheduler_job()
            else:
                logger.info("⚠️ Scheduler Job Worker 비활성화 (ENABLE_BUY_SCANNER_JOB_WORKER=false)")
        
        logger.info("=== Buy Scanner Service 초기화 완료 ===")
        return True
        
    except Exception as e:
        logger.critical(f"❌ 초기화 실패: {e}", exc_info=True)
        return False


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
                    
                    # 연결 유지 루프
                    while kis_client.websocket.connection_event.is_set() and not opportunity_watcher.stop_event.is_set():
                        time.sleep(1)
                        now = time.time()
                        
                        # Heartbeat 발행 (5초마다)
                        if now - last_heartbeat_time >= 5:
                            opportunity_watcher.publish_heartbeat()
                            last_heartbeat_time = now
                    
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
            
            # 연결 유지 루프
            while connection_event.is_set() and not opportunity_watcher.stop_event.is_set():
                time.sleep(1)
                now = time.time()
                
                # Heartbeat 발행 (5초마다)
                if now - last_heartbeat_time >= 5:
                    opportunity_watcher.publish_heartbeat()
                    last_heartbeat_time = now
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
    if not opportunity_watcher:
        return
    
    # 매수 신호 체크
    signal = opportunity_watcher.on_price_update(stock_code, current_price, volume=0)
    
    if signal:
        # 매수 신호 발행
        opportunity_watcher.publish_signal(signal)


@app.route('/health', methods=['GET'])
def health_check():
    if scanner and rabbitmq_publisher:
        return jsonify({"status": "ok", "service": "buy-scanner"}), 200
    else:
        return jsonify({"status": "initializing"}), 503


def _perform_scan(trigger_source: str = "manual") -> dict:
    """Scanner 실행 및 RabbitMQ 발행 (공용 로직)"""
    if not scanner or not rabbitmq_publisher:
        raise RuntimeError("Service not initialized")
    
    # Telegram 명령으로 설정된 Trading Flag 체크
    if redis_cache.is_trading_stopped():
        logger.warning("🛑 긴급 중지 상태입니다. 스캔을 건너뜁니다.")
        return {"status": "trading_stopped", "reason": "Emergency stop active"}
    
    if redis_cache.is_trading_paused():
        pause_info = redis_cache.get_trading_flag('pause')
        reason = pause_info.get('reason', '사용자 요청')
        logger.warning(f"⏸️ 매수 일시 중지 상태입니다. 스캔을 건너뜁니다. (사유: {reason})")
        return {"status": "trading_paused", "reason": reason}

    # 장 운영 여부 확인 (가능한 경우) — mock/test에서는 스킵 가능
    disable_market_open_check = scanner.config.get_bool("DISABLE_MARKET_OPEN_CHECK", default=False)
    is_mock_mode = os.getenv("TRADING_MODE", "REAL").lower() == "mock"
    if not disable_market_open_check and not is_mock_mode:
        try:
            if hasattr(scanner.kis, "check_market_open"):
                if not scanner.kis.check_market_open():
                    logger.warning("💤 시장 미운영(휴장/주말/장외)으로 스캔을 건너뜁니다.")
                    return {"status": "market_closed", "dry_run": True}
            else:
                # Gateway 클라이언트인 경우 최소한 주말/시간 필터 적용
                from datetime import datetime
                import pytz
                kst = pytz.timezone("Asia/Seoul")
                now = datetime.now(kst)
                if not (0 <= now.weekday() <= 4 and 8 <= now.hour <= 16):
                    logger.warning("💤 시장 미운영 시간(주말/장외)으로 스캔을 건너뜁니다.")
                    return {"status": "market_closed", "dry_run": True}
        except Exception as e:
            logger.error(f"시장 운영 여부 확인 실패: {e}", exc_info=True)
            # 체크 실패 시 안전하게 스캔을 중단
            return {"status": "market_check_failed", "error": str(e)}

    dry_run = os.getenv("DRY_RUN", "true").lower() == "true"
    logger.info("=== 매수 신호 스캔 시작 (trigger=%s) ===", trigger_source)
    scan_result = scanner.scan_buy_opportunities()

    if not scan_result or not scan_result.get("candidates"):
        logger.info("매수 후보가 없습니다.")
        return {"status": "no_candidates", "dry_run": dry_run}

    # [Phase 1] Safety Separation Logic
    # 1. Config Check
    disable_direct_buy = scanner.config.get_bool("DISABLE_DIRECT_BUY", default=True)
    
    # 2. Monitor Heartbeat Check (Auto-Fallback)
    monitor_alive = False
    try:
        # DB Facade를 통해 Redis 연결 (shared.rabbitmq가 아님)
        # NOTE: ConfigManager 인스턴스(scanner.config)가 있지만, 여기서는 직접 Connection이 필요
        redis_client = database.get_redis_connection()
        if redis_client:
            # OpportunityWatcher Heartbeat Key
            heartbeat_data = redis_client.get("monitoring:opportunity_watcher")
            if heartbeat_data:
                monitor_alive = True
            else:
                logger.warning("⚠️ OpportunityWatcher Heartbeat 없음 - Monitor가 죽은 것으로 판단")
    except Exception as e:
        logger.warning(f"Heartbeat 체크 실패: {e}")
        # Redis 오류 등 불확실할 때는 안전하게(alive=False) 간주하여 Fallback? 
        # 아니면 중복 방지 우선? -> 안전하게 Fallback(직접 발송)을 활성화하는 것이 맞음.
        monitor_alive = False

    message_id = None
    should_publish = True
    
    if disable_direct_buy:
        if monitor_alive:
            should_publish = False
            logger.info("🛡️ [Safety Mode] Monitor 정상작동 중이므로 직접 매수 신호 발송을 건너뜁니다.")
            # Shadow Mode (Log Only)
            logger.info(f"👻 [Shadow] 매수 신호 내용: {scan_result}")
        else:
            logger.warning("🚨 [Fallback Mode] Monitor 비정상 감지! 직접 매수 신호를 발송합니다.")
            should_publish = True
    
    if should_publish:
        message_id = rabbitmq_publisher.publish(scan_result)
        if not message_id:
            raise RuntimeError("Failed to publish buy signal to RabbitMQ")

        logger.info(
            "✅ 매수 신호 발행 완료 (ID: %s, 후보 %d개)",
            message_id,
            len(scan_result["candidates"]),
        )
    
    return {
        "status": "success",
        "message_id": message_id,
        "candidates_count": len(scan_result["candidates"]),
        "market_regime": scan_result.get("market_regime"),
        "dry_run": dry_run,
        "direct_buy_disabled": disable_direct_buy,
        "fallback_active": (disable_direct_buy and not monitor_alive)
    }


@app.route('/scan', methods=['POST'])
def scan():
    """매수 신호 스캔"""
    try:
        result = _perform_scan(trigger_source="http")
        http_status = 200 if result.get("status") != "error" else 500
        return jsonify(result), http_status
    except RuntimeError as err:
        logger.error("❌ /scan 처리 중 오류: %s", err, exc_info=True)
        return jsonify({"status": "error", "error": str(err)}), 500
    except Exception as e:
        logger.error(f"❌ /scan 처리 중 예외: {e}", exc_info=True)
        return jsonify({"status": "error", "error": str(e)}), 500


def _get_scheduler_job_id() -> str:
    return os.getenv("SCHEDULER_BUY_SCANNER_JOB_ID", "buy-scanner")


def _bootstrap_scheduler_job():
    """서비스 기동 시 1회 실행 메시지를 발행."""
    if not scheduler_job_publisher:
        logger.warning("⚠️ Scheduler Job Publisher 없음. Bootstrap을 건너뜁니다.")
        return

    job_id = _get_scheduler_job_id()
    payload = {
        "job_id": job_id,
        "scope": os.getenv("SCHEDULER_SCOPE", "real"),
        "run_id": str(uuid.uuid4()),
        "trigger_source": "startup_oneshot",
        "params": {},
        "timeout_sec": 180,
        "retry_limit": 1,
        "queued_at": datetime.now(timezone.utc).isoformat(),
    }

    message_id = scheduler_job_publisher.publish(payload)
    if message_id:
        logger.info("🚀 Buy Scanner Startup Job 발행 (job=%s, message=%s)", job_id, message_id)
    else:
        logger.error("❌ Buy Scanner Startup Job 발행 실패 (job=%s)", job_id)


def handle_scheduler_job_message(payload: dict):
    """Scheduler Queue에서 전달된 Job 처리"""
    job_msg = parse_job_message(payload)
    # "unknown"일 때도 환경변수 job_id 사용
    effective_job_id = job_msg.job_id if job_msg.job_id and job_msg.job_id != "unknown" else _get_scheduler_job_id()
    logger.info(
        "🕒 Scheduler Job 수신: job=%s (effective=%s) run=%s trigger=%s delay=%s",
        job_msg.job_id,
        effective_job_id,
        job_msg.run_id,
        job_msg.trigger_source,
        job_msg.next_delay_sec,
    )

    try:
        _perform_scan(trigger_source=f"scheduler/{job_msg.trigger_source}")
        logger.info("✅ Scheduler Job 처리 완료: job=%s", effective_job_id)
    except Exception as exc:
        logger.error("❌ Scheduler Job 실패: %s", exc, exc_info=True)
    finally:
        mark_job_run(effective_job_id, scope=job_msg.scope)


@app.route('/', methods=['GET'])
def root():
    return jsonify({
        "service": "buy-scanner",
        "version": "v1.0",
        "trading_mode": os.getenv("TRADING_MODE", "MOCK"),
        "dry_run": os.getenv("DRY_RUN", "true")
    }), 200


if scanner is None and os.getenv('WERKZEUG_RUN_MAIN') != 'true':
    logger.info("모듈 로드 시 서비스 초기화 시작")
    if not initialize_service():
        logger.critical("서비스 초기화 실패")
        raise RuntimeError("Service initialization failed")

if __name__ == '__main__':
    if scanner is None:
        if not initialize_service():
            sys.exit(1)
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port, debug=False)
