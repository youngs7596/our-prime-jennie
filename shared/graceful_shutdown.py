"""
shared/graceful_shutdown.py - Graceful Shutdown Handler
=======================================================

이 모듈은 서비스의 우아한 종료를 지원합니다.

주요 기능:
---------
1. SIGTERM/SIGINT 신호 처리
2. 진행 중인 작업 완료 대기
3. 종료 상태 추적 및 Health Check 연동

사용 예시:
---------
>>> from shared.graceful_shutdown import GracefulShutdown
>>>
>>> shutdown_handler = GracefulShutdown(timeout=30)
>>>
>>> # 메인 루프에서 사용
>>> while not shutdown_handler.is_shutting_down():
...     process_work()
...
>>> # 종료 대기
>>> shutdown_handler.wait_for_in_flight_tasks()
"""

import logging
import signal
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Optional

logger = logging.getLogger(__name__)


@dataclass
class ShutdownState:
    """종료 상태 추적"""
    shutdown_requested: bool = False
    shutdown_time: Optional[datetime] = None
    in_flight_tasks: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def request_shutdown(self):
        with self._lock:
            self.shutdown_requested = True
            self.shutdown_time = datetime.now()

    def increment_tasks(self):
        with self._lock:
            self.in_flight_tasks += 1
            return self.in_flight_tasks

    def decrement_tasks(self):
        with self._lock:
            self.in_flight_tasks = max(0, self.in_flight_tasks - 1)
            return self.in_flight_tasks

    def get_in_flight_count(self) -> int:
        with self._lock:
            return self.in_flight_tasks


class GracefulShutdown:
    """
    Graceful Shutdown Handler

    서비스가 SIGTERM/SIGINT 신호를 받으면:
    1. 새로운 작업 수락 중단
    2. 진행 중인 작업 완료 대기
    3. 리소스 정리 후 종료
    """

    def __init__(
        self,
        timeout: int = 30,
        on_shutdown: Optional[Callable[[], None]] = None,
        service_name: str = "unknown"
    ):
        """
        Args:
            timeout: 종료 대기 최대 시간 (초)
            on_shutdown: 종료 시 호출될 콜백 함수
            service_name: 서비스 이름 (로깅용)
        """
        self.timeout = timeout
        self.on_shutdown = on_shutdown
        self.service_name = service_name
        self.state = ShutdownState()
        self.shutdown_event = threading.Event()
        self._start_time = datetime.now()

        # 시그널 핸들러 등록
        self._register_signal_handlers()

        logger.info(
            "[GracefulShutdown] %s: 초기화 완료 (timeout=%ds)",
            service_name, timeout
        )

    def _register_signal_handlers(self):
        """SIGTERM/SIGINT 시그널 핸들러 등록"""
        # 메인 스레드에서만 시그널 핸들러 등록 가능
        try:
            signal.signal(signal.SIGTERM, self._handle_shutdown_signal)
            signal.signal(signal.SIGINT, self._handle_shutdown_signal)
            logger.debug("[GracefulShutdown] 시그널 핸들러 등록 완료")
        except ValueError:
            # 메인 스레드가 아닌 경우 무시
            logger.warning(
                "[GracefulShutdown] 시그널 핸들러 등록 실패 (메인 스레드 아님)"
            )

    def _handle_shutdown_signal(self, signum: int, frame):
        """시그널 수신 시 호출"""
        signal_name = signal.Signals(signum).name
        logger.info(
            "🛑 [GracefulShutdown] %s: %s 수신, graceful shutdown 시작...",
            self.service_name, signal_name
        )

        self.state.request_shutdown()
        self.shutdown_event.set()

        # 사용자 정의 콜백 실행
        if self.on_shutdown:
            try:
                self.on_shutdown()
            except Exception as e:
                logger.error(
                    "[GracefulShutdown] on_shutdown 콜백 오류: %s", e
                )

    def is_shutting_down(self) -> bool:
        """종료 진행 중인지 확인"""
        return self.state.shutdown_requested

    def request_shutdown(self):
        """프로그래밍 방식으로 종료 요청"""
        logger.info(
            "[GracefulShutdown] %s: 프로그래밍 방식 종료 요청",
            self.service_name
        )
        self.state.request_shutdown()
        self.shutdown_event.set()

        if self.on_shutdown:
            try:
                self.on_shutdown()
            except Exception as e:
                logger.error("[GracefulShutdown] on_shutdown 콜백 오류: %s", e)

    def track_task_start(self) -> int:
        """작업 시작 추적 (반환: 현재 진행 중인 작업 수)"""
        count = self.state.increment_tasks()
        logger.debug(
            "[GracefulShutdown] %s: 작업 시작 (in_flight=%d)",
            self.service_name, count
        )
        return count

    def track_task_end(self) -> int:
        """작업 완료 추적 (반환: 현재 진행 중인 작업 수)"""
        count = self.state.decrement_tasks()
        logger.debug(
            "[GracefulShutdown] %s: 작업 완료 (in_flight=%d)",
            self.service_name, count
        )
        return count

    def get_in_flight_tasks(self) -> int:
        """현재 진행 중인 작업 수 반환"""
        return self.state.get_in_flight_count()

    def get_uptime_seconds(self) -> float:
        """서비스 가동 시간 (초) 반환"""
        return (datetime.now() - self._start_time).total_seconds()

    def wait_for_shutdown(self, timeout: Optional[int] = None) -> bool:
        """
        종료 신호 대기

        Args:
            timeout: 대기 시간 (초). None이면 인스턴스 기본값 사용

        Returns:
            True if shutdown signal received, False if timeout
        """
        wait_timeout = timeout if timeout is not None else self.timeout
        return self.shutdown_event.wait(timeout=wait_timeout)

    def wait_for_in_flight_tasks(self, poll_interval: float = 0.5) -> bool:
        """
        진행 중인 작업 완료 대기

        Args:
            poll_interval: 상태 체크 간격 (초)

        Returns:
            True if all tasks completed, False if timeout
        """
        deadline = time.time() + self.timeout

        while time.time() < deadline:
            in_flight = self.state.get_in_flight_count()

            if in_flight == 0:
                logger.info(
                    "✅ [GracefulShutdown] %s: 모든 작업 완료, 종료 준비 완료",
                    self.service_name
                )
                return True

            remaining = deadline - time.time()
            logger.info(
                "⏳ [GracefulShutdown] %s: %d개 작업 진행 중, %.1f초 남음",
                self.service_name, in_flight, remaining
            )
            time.sleep(min(poll_interval, remaining))

        in_flight = self.state.get_in_flight_count()
        if in_flight > 0:
            logger.warning(
                "⚠️ [GracefulShutdown] %s: 타임아웃! %d개 작업 미완료 상태로 종료",
                self.service_name, in_flight
            )
        return False

    def get_health_status(self) -> dict:
        """
        Health Check용 상태 정보 반환

        Returns:
            dict: {
                "shutting_down": bool,
                "in_flight_tasks": int,
                "uptime_seconds": float,
                "ready": bool  # 새 작업 수락 가능 여부
            }
        """
        is_shutting_down = self.is_shutting_down()
        return {
            "shutting_down": is_shutting_down,
            "in_flight_tasks": self.get_in_flight_tasks(),
            "uptime_seconds": round(self.get_uptime_seconds(), 1),
            "ready": not is_shutting_down  # 종료 중이면 ready=False
        }


class TaskTracker:
    """
    컨텍스트 매니저로 작업 추적을 쉽게 하기 위한 헬퍼 클래스

    사용 예시:
    ---------
    >>> shutdown = GracefulShutdown(service_name="my-service")
    >>> tracker = TaskTracker(shutdown)
    >>>
    >>> with tracker.track():
    ...     process_order()  # 이 블록 동안 in_flight_tasks += 1
    """

    def __init__(self, shutdown_handler: GracefulShutdown):
        self.shutdown_handler = shutdown_handler

    class _TaskContext:
        def __init__(self, handler: GracefulShutdown):
            self.handler = handler

        def __enter__(self):
            self.handler.track_task_start()
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            self.handler.track_task_end()
            return False

    def track(self):
        """작업 추적 컨텍스트 매니저 반환"""
        return self._TaskContext(self.shutdown_handler)


# 모듈 레벨 편의 함수
_global_shutdown: Optional[GracefulShutdown] = None


def init_global_shutdown(
    timeout: int = 30,
    on_shutdown: Optional[Callable[[], None]] = None,
    service_name: str = "unknown"
) -> GracefulShutdown:
    """
    전역 GracefulShutdown 인스턴스 초기화

    싱글톤 패턴으로 서비스당 하나의 인스턴스만 생성
    """
    global _global_shutdown
    if _global_shutdown is None:
        _global_shutdown = GracefulShutdown(
            timeout=timeout,
            on_shutdown=on_shutdown,
            service_name=service_name
        )
    return _global_shutdown


def get_global_shutdown() -> Optional[GracefulShutdown]:
    """전역 GracefulShutdown 인스턴스 반환 (없으면 None)"""
    return _global_shutdown
