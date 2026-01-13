# shared/kis/circuit_breaker.py
# KIS API Circuit Breaker 패턴 구현

"""
Circuit Breaker Pattern for KIS API

KIS API 연속 실패 시 자동 차단하여 시스템 안정성 보장
- CLOSED: 정상 상태, 모든 요청 통과
- OPEN: 장애 상태, 모든 요청 즉시 거부 (fast-fail)
- HALF_OPEN: 복구 테스트, 제한된 요청만 허용

사용법:
    from shared.kis.circuit_breaker import circuit_breaker
    
    @circuit_breaker.protect
    def call_kis_api():
        return kis.get_stock_price(...)
"""

import time
import logging
import threading
from enum import Enum
from functools import wraps
from typing import Callable, TypeVar, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

T = TypeVar('T')


class CircuitState(Enum):
    """Circuit Breaker 상태"""
    CLOSED = "CLOSED"      # 정상 - 모든 요청 통과
    OPEN = "OPEN"          # 장애 - 요청 거부
    HALF_OPEN = "HALF_OPEN"  # 복구 테스트


@dataclass
class CircuitBreakerConfig:
    """Circuit Breaker 설정"""
    failure_threshold: int = 5      # OPEN 전환 실패 횟수
    success_threshold: int = 3       # CLOSED 전환 성공 횟수
    timeout_seconds: float = 30.0    # OPEN 상태 유지 시간
    half_open_max_calls: int = 3     # HALF_OPEN 시 최대 테스트 호출 수
    
    # Exponential Backoff 설정
    initial_backoff: float = 1.0     # 초기 백오프 (초)
    max_backoff: float = 60.0        # 최대 백오프 (초)
    backoff_multiplier: float = 2.0  # 백오프 증가 배수


class CircuitBreakerError(Exception):
    """Circuit이 OPEN 상태일 때 발생"""
    def __init__(self, message: str, state: CircuitState, retry_after: float):
        super().__init__(message)
        self.state = state
        self.retry_after = retry_after


@dataclass
class CircuitBreaker:
    """Circuit Breaker 구현"""
    name: str
    config: CircuitBreakerConfig = field(default_factory=CircuitBreakerConfig)
    
    # 내부 상태
    _state: CircuitState = field(default=CircuitState.CLOSED, init=False)
    _failure_count: int = field(default=0, init=False)
    _success_count: int = field(default=0, init=False)
    _last_failure_time: float = field(default=0.0, init=False)
    _current_backoff: float = field(default=0.0, init=False)  # __post_init__에서 초기화
    _half_open_calls: int = field(default=0, init=False)
    _open_count: int = field(default=0, init=False)  # OPEN 전환 횟수 (exponential backoff용)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)
    
    def __post_init__(self):
        """dataclass 초기화 후 backoff 초기값 설정"""
        self._current_backoff = self.config.initial_backoff
    
    @property
    def state(self) -> CircuitState:
        return self._state
    
    @property
    def is_available(self) -> bool:
        """요청 가능 여부"""
        with self._lock:
            return self._check_and_update_state()
    
    def _check_and_update_state(self) -> bool:
        """상태 확인 및 업데이트 (lock 내부에서 호출)"""
        if self._state == CircuitState.CLOSED:
            return True
        
        if self._state == CircuitState.OPEN:
            # 타임아웃 경과 시 HALF_OPEN 전환
            elapsed = time.time() - self._last_failure_time
            if elapsed >= self._current_backoff:
                self._transition_to_half_open()
                return True
            return False
        
        if self._state == CircuitState.HALF_OPEN:
            # 최대 테스트 호출 수 미만이면 허용
            return self._half_open_calls < self.config.half_open_max_calls
        
        return False
    
    def _transition_to_half_open(self):
        """HALF_OPEN 상태로 전환"""
        logger.info(f"⚡ [{self.name}] Circuit: OPEN → HALF_OPEN (복구 테스트 시작)")
        self._state = CircuitState.HALF_OPEN
        self._half_open_calls = 0
        self._success_count = 0
    
    def record_success(self):
        """성공 기록"""
        with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self.config.success_threshold:
                    self._transition_to_closed()
            elif self._state == CircuitState.CLOSED:
                # 성공 시 실패 카운트 감소
                self._failure_count = max(0, self._failure_count - 1)
    
    def record_failure(self, error: Optional[Exception] = None):
        """실패 기록"""
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()
            
            if self._state == CircuitState.HALF_OPEN:
                # HALF_OPEN에서 실패 → 즉시 OPEN
                self._transition_to_open()
            elif self._state == CircuitState.CLOSED:
                if self._failure_count >= self.config.failure_threshold:
                    self._transition_to_open()
            
            logger.warning(f"⚠️ [{self.name}] API 실패 #{self._failure_count}: {error}")
    
    def _transition_to_open(self):
        """OPEN 상태로 전환"""
        was_already_open = self._state == CircuitState.OPEN
        self._state = CircuitState.OPEN
        self._open_count += 1
        
        # Exponential Backoff 적용 (HALF_OPEN에서 다시 OPEN이 될 때만 증가)
        if was_already_open or self._open_count > 1:
            # 연속 실패 - backoff 증가
            self._current_backoff = min(
                self._current_backoff * self.config.backoff_multiplier,
                self.config.max_backoff
            )
        else:
            # 첫 번째 OPEN - initial backoff 사용
            self._current_backoff = self.config.initial_backoff
        
        logger.error(
            f"🔴 [{self.name}] Circuit OPEN! "
            f"실패 횟수: {self._failure_count}, "
            f"재시도: {self._current_backoff:.1f}초 후"
        )
    
    def _transition_to_closed(self):
        """클LOSED 상태로 복구"""
        logger.info(f"🟢 [{self.name}] Circuit: HALF_OPEN → CLOSED (정상 복구)")
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._open_count = 0  # OPEN 전환 횟수 리셋 
        self._current_backoff = self.config.initial_backoff
    
    def protect(self, func: Callable[..., T]) -> Callable[..., T]:
        """데코레이터: 함수를 Circuit Breaker로 보호"""
        @wraps(func)
        def wrapper(*args, **kwargs) -> T:
            if not self.is_available:
                retry_after = self._current_backoff - (time.time() - self._last_failure_time)
                raise CircuitBreakerError(
                    f"Circuit [{self.name}] is OPEN. Retry after {retry_after:.1f}s",
                    state=self._state,
                    retry_after=max(0, retry_after)
                )
            
            if self._state == CircuitState.HALF_OPEN:
                with self._lock:
                    self._half_open_calls += 1
            
            try:
                result = func(*args, **kwargs)
                self.record_success()
                return result
            except Exception as e:
                self.record_failure(e)
                raise
        
        return wrapper
    
    def reset(self):
        """수동 리셋 (테스트/관리용)"""
        with self._lock:
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._success_count = 0
            self._open_count = 0
            self._current_backoff = self.config.initial_backoff
            logger.info(f"🔄 [{self.name}] Circuit 수동 리셋됨")
    
    def get_status(self) -> dict:
        """현재 상태 반환"""
        with self._lock:
            return {
                'name': self.name,
                'state': self._state.value,
                'failure_count': self._failure_count,
                'success_count': self._success_count,
                'current_backoff': self._current_backoff,
                'is_available': self._check_and_update_state()
            }


# 글로벌 Circuit Breaker 인스턴스 (KIS API용)
_kis_circuit_breaker: Optional[CircuitBreaker] = None


def get_kis_circuit_breaker() -> CircuitBreaker:
    """KIS API Circuit Breaker 싱글톤"""
    global _kis_circuit_breaker
    if _kis_circuit_breaker is None:
        _kis_circuit_breaker = CircuitBreaker(
            name="KIS_API",
            config=CircuitBreakerConfig(
                failure_threshold=5,
                success_threshold=3,
                timeout_seconds=30.0,
                initial_backoff=5.0,
                max_backoff=120.0
            )
        )
    return _kis_circuit_breaker
