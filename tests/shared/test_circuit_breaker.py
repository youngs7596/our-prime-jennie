# tests/shared/test_circuit_breaker.py
# Circuit Breaker 유닛 테스트

import pytest
import time
from unittest.mock import MagicMock
from shared.kis.circuit_breaker import (
    CircuitBreaker, 
    CircuitBreakerConfig, 
    CircuitBreakerError,
    CircuitState,
    get_kis_circuit_breaker
)


class TestCircuitBreaker:
    """CircuitBreaker 테스트"""
    
    @pytest.fixture
    def cb(self):
        """짧은 타임아웃의 테스트용 Circuit Breaker"""
        return CircuitBreaker(
            name="TEST_CB",
            config=CircuitBreakerConfig(
                failure_threshold=3,
                success_threshold=2,
                timeout_seconds=0.1,  # 빠른 테스트를 위해 짧게
                half_open_max_calls=2,
                initial_backoff=0.05,  # 작은 값으로 시작 (2배되어도 0.1)
                max_backoff=1.0,
                backoff_multiplier=2.0
            )
        )
    
    def test_initial_state_closed(self, cb):
        """초기 상태: CLOSED"""
        assert cb.state == CircuitState.CLOSED
        assert cb.is_available is True
    
    def test_failure_threshold_triggers_open(self, cb):
        """실패 임계값 도달 시 OPEN 전환"""
        for i in range(3):
            cb.record_failure(Exception(f"Error {i}"))
        
        assert cb.state == CircuitState.OPEN
        assert cb.is_available is False
    
    def test_open_to_half_open_after_timeout(self, cb):
        """타임아웃 후 HALF_OPEN 전환"""
        # OPEN 상태로 만들기
        for i in range(3):
            cb.record_failure()
        
        assert cb.state == CircuitState.OPEN
        
        # 타임아웃 대기 (initial_backoff * multiplier = 0.05 * 2 = 0.1)
        time.sleep(0.15)
        
        # is_available 확인 시 HALF_OPEN 전환
        assert cb.is_available is True
        assert cb.state == CircuitState.HALF_OPEN
    
    def test_half_open_success_to_closed(self, cb):
        """HALF_OPEN에서 성공 시 CLOSED 전환"""
        # OPEN → HALF_OPEN
        for i in range(3):
            cb.record_failure()
        time.sleep(0.15)  # backoff = 0.1
        _ = cb.is_available  # 트리거
        
        assert cb.state == CircuitState.HALF_OPEN
        
        # 성공 기록
        cb.record_success()
        cb.record_success()
        
        assert cb.state == CircuitState.CLOSED
    
    def test_half_open_failure_to_open(self, cb):
        """HALF_OPEN에서 실패 시 즉시 OPEN 전환"""
        # OPEN → HALF_OPEN
        for i in range(3):
            cb.record_failure()
        time.sleep(0.15)  # backoff = 0.1
        _ = cb.is_available
        
        assert cb.state == CircuitState.HALF_OPEN
        
        # 실패 기록
        cb.record_failure()
        
        assert cb.state == CircuitState.OPEN
    
    def test_protect_decorator_success(self, cb):
        """protect 데코레이터: 성공 케이스"""
        @cb.protect
        def success_func():
            return "success"
        
        result = success_func()
        
        assert result == "success"
        assert cb.state == CircuitState.CLOSED
    
    def test_protect_decorator_failure(self, cb):
        """protect 데코레이터: 실패 케이스"""
        @cb.protect
        def fail_func():
            raise ValueError("Test error")
        
        with pytest.raises(ValueError):
            fail_func()
        
        # 실패 기록됨
        status = cb.get_status()
        assert status['failure_count'] == 1
    
    def test_protect_decorator_circuit_open(self, cb):
        """protect 데코레이터: OPEN 시 즉시 거부"""
        # OPEN 상태로 만들기
        for i in range(3):
            cb.record_failure()
        
        @cb.protect
        def any_func():
            return "should not reach"
        
        with pytest.raises(CircuitBreakerError) as exc_info:
            any_func()
        
        assert exc_info.value.state == CircuitState.OPEN
    
    def test_exponential_backoff(self, cb):
        """Exponential Backoff 검증"""
        # 첫 번째 OPEN (initial_backoff = 0.05)
        for i in range(3):
            cb.record_failure()
        
        status1 = cb.get_status()
        backoff1 = status1['current_backoff']
        assert backoff1 == 0.05  # 첫 OPEN은 initial_backoff
        
        # 복구 → HALF_OPEN → 다시 실패하면 backoff 증가
        time.sleep(0.1)  # backoff = 0.05초 대기
        _ = cb.is_available  # HALF_OPEN으로 전환
        assert cb.state == CircuitState.HALF_OPEN
        
        # HALF_OPEN에서 실패 → 다시 OPEN (backoff 증가)
        cb.record_failure()
        
        assert cb.state == CircuitState.OPEN
        status2 = cb.get_status()
        backoff2 = status2['current_backoff']
        
        # 백오프 증가 확인: 0.05 * 2 = 0.1
        assert backoff2 == backoff1 * cb.config.backoff_multiplier
    
    def test_reset(self, cb):
        """수동 리셋"""
        for i in range(3):
            cb.record_failure()
        
        assert cb.state == CircuitState.OPEN
        
        cb.reset()
        
        assert cb.state == CircuitState.CLOSED
        assert cb.get_status()['failure_count'] == 0
    
    def test_get_status(self, cb):
        """상태 조회"""
        status = cb.get_status()
        
        assert 'name' in status
        assert 'state' in status
        assert 'failure_count' in status
        assert 'is_available' in status
        assert status['name'] == "TEST_CB"


class TestCircuitBreakerSingleton:
    """KIS Circuit Breaker 싱글톤 테스트"""
    
    def test_singleton_instance(self):
        """싱글톤 확인"""
        cb1 = get_kis_circuit_breaker()
        cb2 = get_kis_circuit_breaker()
        
        assert cb1 is cb2
        assert cb1.name == "KIS_API"
    
    def test_config_values(self):
        """기본 설정값 확인"""
        cb = get_kis_circuit_breaker()
        
        assert cb.config.failure_threshold == 5
        assert cb.config.success_threshold == 3
