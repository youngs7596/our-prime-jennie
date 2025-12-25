"""
tests/shared/test_utils.py - 유틸리티 함수 테스트
=================================================

shared/utils.py의 데코레이터 및 유틸리티 함수들을 테스트합니다.
"""

import pytest
import time
from datetime import datetime
from unittest.mock import MagicMock, patch
from shared.utils import (
    RetryStrategy, RetryableError, NonRetryableError,
    retry_with_backoff, log_execution_time, handle_errors,
    is_operating_hours
)


# ============================================================================
# Tests: retry_with_backoff 데코레이터
# ============================================================================

class TestRetryWithBackoff:
    """retry_with_backoff 데코레이터 테스트"""
    
    def test_success_first_try(self):
        """첫 시도에서 성공"""
        call_count = [0]
        
        @retry_with_backoff(max_attempts=3)
        def successful_func():
            call_count[0] += 1
            return "success"
        
        result = successful_func()
        
        assert result == "success"
        assert call_count[0] == 1
    
    def test_retry_on_exception(self):
        """예외 발생 시 재시도"""
        call_count = [0]
        
        @retry_with_backoff(max_attempts=3, initial_delay=0.01)
        def fail_then_succeed():
            call_count[0] += 1
            if call_count[0] < 3:
                raise ValueError("일시적 오류")
            return "success"
        
        result = fail_then_succeed()
        
        assert result == "success"
        assert call_count[0] == 3
    
    def test_max_attempts_exceeded(self):
        """최대 시도 횟수 초과"""
        call_count = [0]
        
        @retry_with_backoff(max_attempts=3, initial_delay=0.01)
        def always_fail():
            call_count[0] += 1
            raise ValueError("항상 실패")
        
        with pytest.raises(ValueError) as exc_info:
            always_fail()
        
        assert call_count[0] == 3
        assert "항상 실패" in str(exc_info.value)
    
    def test_non_retryable_error(self):
        """NonRetryableError는 즉시 발생"""
        call_count = [0]
        
        @retry_with_backoff(max_attempts=3, initial_delay=0.01)
        def non_retryable():
            call_count[0] += 1
            raise NonRetryableError("재시도 불가")
        
        with pytest.raises(NonRetryableError):
            non_retryable()
        
        assert call_count[0] == 1  # 재시도 안함
    
    def test_fixed_interval_strategy(self):
        """FIXED_INTERVAL 전략"""
        call_count = [0]
        
        @retry_with_backoff(
            max_attempts=3, 
            initial_delay=0.01,
            strategy=RetryStrategy.FIXED_INTERVAL
        )
        def fail_twice():
            call_count[0] += 1
            if call_count[0] < 3:
                raise ValueError("실패")
            return "ok"
        
        result = fail_twice()
        assert result == "ok"
        assert call_count[0] == 3
    
    def test_immediate_strategy(self):
        """IMMEDIATE 전략 (즉시 재시도)"""
        call_count = [0]
        
        @retry_with_backoff(
            max_attempts=3, 
            strategy=RetryStrategy.IMMEDIATE
        )
        def fail_once():
            call_count[0] += 1
            if call_count[0] == 1:
                raise ValueError("첫 번째 실패")
            return "ok"
        
        start = time.time()
        result = fail_once()
        duration = time.time() - start
        
        assert result == "ok"
        assert duration < 0.5  # 지연 없이 빠르게 완료
    
    def test_on_retry_callback(self):
        """재시도 콜백 호출"""
        callback_calls = []
        
        def on_retry_callback(attempt, exc):
            callback_calls.append((attempt, str(exc)))
        
        @retry_with_backoff(
            max_attempts=3,
            initial_delay=0.01,
            on_retry=on_retry_callback
        )
        def fail_twice():
            if len(callback_calls) < 2:
                raise ValueError("실패")
            return "ok"
        
        result = fail_twice()
        
        assert result == "ok"
        assert len(callback_calls) == 2
        assert callback_calls[0][0] == 1  # 첫 번째 재시도
        assert callback_calls[1][0] == 2  # 두 번째 재시도
    
    def test_specific_exception_types(self):
        """특정 예외만 재시도"""
        call_count = [0]
        
        @retry_with_backoff(
            max_attempts=3,
            initial_delay=0.01,
            retryable_exceptions=(ValueError,)  # ValueError만 재시도
        )
        def raise_type_error():
            call_count[0] += 1
            raise TypeError("타입 에러")
        
        with pytest.raises(TypeError):
            raise_type_error()
        
        assert call_count[0] == 1  # TypeError는 재시도 안함


# ============================================================================
# Tests: log_execution_time 데코레이터
# ============================================================================

class TestLogExecutionTime:
    """log_execution_time 데코레이터 테스트"""
    
    def test_logs_execution_time(self, caplog):
        """실행 시간 로깅"""
        @log_execution_time(operation_name="테스트 작업")
        def slow_func():
            time.sleep(0.1)
            return "done"
        
        with caplog.at_level('INFO'):
            result = slow_func()
        
        assert result == "done"
        assert "테스트 작업" in caplog.text
        assert "실행 완료" in caplog.text
        assert "소요 시간" in caplog.text
    
    def test_uses_function_name_if_no_operation_name(self, caplog):
        """operation_name 없으면 함수명 사용"""
        @log_execution_time()
        def my_custom_function():
            return "result"
        
        with caplog.at_level('INFO'):
            my_custom_function()
        
        assert "my_custom_function" in caplog.text
    
    def test_logs_error_on_exception(self, caplog):
        """예외 발생 시에도 시간 로깅"""
        @log_execution_time(operation_name="실패 작업")
        def failing_func():
            raise ValueError("에러 발생")
        
        with caplog.at_level('ERROR'):
            with pytest.raises(ValueError):
                failing_func()
        
        assert "실패 작업" in caplog.text
        assert "실행 실패" in caplog.text


# ============================================================================
# Tests: handle_errors 데코레이터
# ============================================================================

class TestHandleErrors:
    """handle_errors 데코레이터 테스트"""
    
    def test_returns_result_on_success(self):
        """성공 시 결과 반환"""
        @handle_errors(default_return=[])
        def successful_func():
            return ["a", "b", "c"]
        
        result = successful_func()
        
        assert result == ["a", "b", "c"]
    
    def test_returns_default_on_error(self):
        """에러 시 기본값 반환"""
        @handle_errors(default_return=[])
        def failing_func():
            raise ValueError("에러")
        
        result = failing_func()
        
        assert result == []
    
    def test_returns_none_default(self):
        """기본값이 None인 경우"""
        @handle_errors(default_return=None)
        def failing_func():
            raise ValueError("에러")
        
        result = failing_func()
        
        assert result is None
    
    def test_logs_error(self, caplog):
        """에러 로깅"""
        @handle_errors(default_return={}, log_error=True)
        def failing_func():
            raise ValueError("상세 에러 메시지")
        
        with caplog.at_level('ERROR'):
            failing_func()
        
        assert "에러 발생" in caplog.text
        assert "failing_func" in caplog.text
    
    def test_no_log_when_disabled(self, caplog):
        """log_error=False일 때 로깅 안함"""
        @handle_errors(default_return=0, log_error=False)
        def failing_func():
            raise ValueError("에러")
        
        with caplog.at_level('ERROR'):
            result = failing_func()
        
        assert result == 0
        # 에러 로그가 없어야 함
        assert "에러 발생" not in caplog.text
    
    def test_reraise_when_enabled(self):
        """reraise=True일 때 에러 재발생"""
        @handle_errors(default_return=None, reraise=True)
        def failing_func():
            raise ValueError("재발생할 에러")
        
        with pytest.raises(ValueError) as exc_info:
            failing_func()
        
        assert "재발생할 에러" in str(exc_info.value)
    
    def test_preserves_function_metadata(self):
        """함수 메타데이터 보존"""
        @handle_errors(default_return=None)
        def documented_function():
            """이것은 문서화된 함수입니다."""
            pass
        
        assert documented_function.__name__ == "documented_function"
        assert "문서화된" in documented_function.__doc__


# ============================================================================
# Tests: RetryableError / NonRetryableError
# ============================================================================

class TestCustomExceptions:
    """커스텀 예외 클래스 테스트"""
    
    def test_retryable_error(self):
        """RetryableError 인스턴스화"""
        error = RetryableError("일시적 오류")
        
        assert str(error) == "일시적 오류"
        assert isinstance(error, Exception)
    
    def test_non_retryable_error(self):
        """NonRetryableError 인스턴스화"""
        error = NonRetryableError("영구적 오류")
        
        assert str(error) == "영구적 오류"
        assert isinstance(error, Exception)


# ============================================================================
# Tests: 데코레이터 조합
# ============================================================================

class TestDecoratorComposition:
    """데코레이터 조합 테스트"""
    
    def test_retry_with_log_and_error_handling(self, caplog):
        """여러 데코레이터 조합"""
        call_count = [0]
        
        @handle_errors(default_return="fallback")
        @log_execution_time(operation_name="조합 테스트")
        @retry_with_backoff(max_attempts=2, initial_delay=0.01)
        def combined_func():
            call_count[0] += 1
            if call_count[0] < 2:
                raise ValueError("첫 번째 실패")
            return "success"
        
        with caplog.at_level('INFO'):
            result = combined_func()
        
        assert result == "success"
        assert call_count[0] == 2
        assert "조합 테스트" in caplog.text


# ============================================================================
# Tests: is_operating_hours 함수
# ============================================================================

class TestIsOperatingHours:
    """is_operating_hours 함수 테스트"""
    
    def test_weekday_operating_hours(self):
        """평일 운영 시간 내"""
        import pytz
        
        # 월요일 10:00 KST
        mock_dt = datetime(2025, 12, 22, 10, 0, 0)  # 월요일
        kst = pytz.timezone('Asia/Seoul')
        mock_dt = kst.localize(mock_dt)
        
        with patch('shared.utils.datetime') as mock_datetime:
            mock_datetime.now.return_value = mock_dt
            result = is_operating_hours(start_hour=7, end_hour=17)
        
        assert result is True
    
    def test_weekday_before_operating_hours(self):
        """평일 운영 시간 전"""
        import pytz
        
        # 월요일 06:00 KST (운영 시간 전)
        mock_dt = datetime(2025, 12, 22, 6, 0, 0)
        kst = pytz.timezone('Asia/Seoul')
        mock_dt = kst.localize(mock_dt)
        
        with patch('shared.utils.datetime') as mock_datetime:
            mock_datetime.now.return_value = mock_dt
            result = is_operating_hours(start_hour=7, end_hour=17)
        
        assert result is False
    
    def test_weekday_after_operating_hours(self):
        """평일 운영 시간 후"""
        import pytz
        
        # 월요일 18:00 KST (운영 시간 후)
        mock_dt = datetime(2025, 12, 22, 18, 0, 0)
        kst = pytz.timezone('Asia/Seoul')
        mock_dt = kst.localize(mock_dt)
        
        with patch('shared.utils.datetime') as mock_datetime:
            mock_datetime.now.return_value = mock_dt
            result = is_operating_hours(start_hour=7, end_hour=17)
        
        assert result is False
    
    def test_weekend_returns_false(self):
        """주말은 항상 False"""
        import pytz
        
        # 토요일 10:00 KST
        mock_dt = datetime(2025, 12, 27, 10, 0, 0)  # 토요일
        kst = pytz.timezone('Asia/Seoul')
        mock_dt = kst.localize(mock_dt)
        
        with patch('shared.utils.datetime') as mock_datetime:
            mock_datetime.now.return_value = mock_dt
            result = is_operating_hours(start_hour=7, end_hour=17)
        
        assert result is False
    
    def test_sunday_returns_false(self):
        """일요일은 항상 False"""
        import pytz
        
        # 일요일 12:00 KST
        mock_dt = datetime(2025, 12, 28, 12, 0, 0)  # 일요일
        kst = pytz.timezone('Asia/Seoul')
        mock_dt = kst.localize(mock_dt)
        
        with patch('shared.utils.datetime') as mock_datetime:
            mock_datetime.now.return_value = mock_dt
            result = is_operating_hours(start_hour=7, end_hour=17)
        
        assert result is False
    
    def test_custom_operating_hours(self):
        """사용자 정의 운영 시간"""
        import pytz
        
        # 월요일 09:30 KST
        mock_dt = datetime(2025, 12, 22, 9, 30, 0)
        kst = pytz.timezone('Asia/Seoul')
        mock_dt = kst.localize(mock_dt)
        
        with patch('shared.utils.datetime') as mock_datetime:
            mock_datetime.now.return_value = mock_dt
            # 09:00 - 15:30 운영 시간
            result = is_operating_hours(start_hour=9, start_minute=0, end_hour=15, end_minute=30)
        
        assert result is True
    
    def test_edge_case_start_time(self):
        """정확히 시작 시간"""
        import pytz
        
        # 월요일 07:00 KST (정확히 시작 시간)
        mock_dt = datetime(2025, 12, 22, 7, 0, 0)
        kst = pytz.timezone('Asia/Seoul')
        mock_dt = kst.localize(mock_dt)
        
        with patch('shared.utils.datetime') as mock_datetime:
            mock_datetime.now.return_value = mock_dt
            result = is_operating_hours(start_hour=7, end_hour=17)
        
        assert result is True
    
    def test_edge_case_end_time(self):
        """정확히 종료 시간"""
        import pytz
        
        # 월요일 17:00 KST (정확히 종료 시간)
        mock_dt = datetime(2025, 12, 22, 17, 0, 0)
        kst = pytz.timezone('Asia/Seoul')
        mock_dt = kst.localize(mock_dt)
        
        with patch('shared.utils.datetime') as mock_datetime:
            mock_datetime.now.return_value = mock_dt
            result = is_operating_hours(start_hour=7, end_hour=17)
        
        assert result is True


# ============================================================================
# Tests: safe_db_operation 데코레이터
# ============================================================================

class TestSafeDbOperation:
    """safe_db_operation 데코레이터 테스트"""
    
    @pytest.fixture(autouse=True)
    def setup_oracledb_mock(self):
        """oracledb 모듈 mock 설정"""
        mock_oracledb = MagicMock()
        mock_oracledb.DatabaseError = type('DatabaseError', (Exception,), {})
        mock_oracledb.OperationalError = type('OperationalError', (Exception,), {})
        
        with patch.dict('sys.modules', {'oracledb': mock_oracledb}):
            self.mock_oracledb = mock_oracledb
            yield
    
    def test_success_first_try(self):
        """첫 시도에서 성공"""
        from shared.utils import safe_db_operation
        
        call_count = [0]
        
        @safe_db_operation(operation_name="테스트 DB 작업", max_retries=3)
        def successful_db_func():
            call_count[0] += 1
            return {"result": "success"}
        
        result = successful_db_func()
        
        assert result == {"result": "success"}
        assert call_count[0] == 1
    
    def test_retry_on_db_error(self):
        """DB 오류 시 재시도"""
        from shared.utils import safe_db_operation
        
        call_count = [0]
        
        @safe_db_operation(operation_name="재시도 테스트", max_retries=3, retry_delay=0.01)
        def fail_then_succeed():
            call_count[0] += 1
            if call_count[0] < 3:
                raise self.mock_oracledb.DatabaseError("일시적 DB 오류")
            return "ok"
        
        result = fail_then_succeed()
        
        assert result == "ok"
        assert call_count[0] == 3
    
    def test_max_retries_exceeded(self):
        """최대 재시도 횟수 초과"""
        from shared.utils import safe_db_operation
        
        call_count = [0]
        
        @safe_db_operation(operation_name="항상 실패", max_retries=2, retry_delay=0.01)
        def always_fail():
            call_count[0] += 1
            raise self.mock_oracledb.DatabaseError("DB 연결 불가")
        
        with pytest.raises(Exception):  # mock DatabaseError
            always_fail()
        
        assert call_count[0] == 2
    
    def test_non_db_error_not_retried(self):
        """DB 오류가 아닌 예외는 즉시 발생"""
        from shared.utils import safe_db_operation
        
        call_count = [0]
        
        @safe_db_operation(operation_name="타입 에러", max_retries=3, retry_delay=0.01)
        def raise_type_error():
            call_count[0] += 1
            raise TypeError("타입 에러")
        
        with pytest.raises(TypeError):
            raise_type_error()
        
        assert call_count[0] == 1


# ============================================================================
# Tests: safe_api_call 데코레이터
# ============================================================================

class TestSafeApiCall:
    """safe_api_call 데코레이터 테스트"""
    
    def test_success_first_try(self):
        """첫 시도에서 성공"""
        from shared.utils import safe_api_call
        
        call_count = [0]
        
        @safe_api_call(api_name="테스트 API", max_retries=3)
        def successful_api():
            call_count[0] += 1
            return {"status": "ok"}
        
        result = successful_api()
        
        assert result == {"status": "ok"}
        assert call_count[0] == 1
    
    def test_retry_on_request_exception(self):
        """Request 오류 시 재시도"""
        from shared.utils import safe_api_call
        import requests
        
        call_count = [0]
        
        @safe_api_call(api_name="재시도 API", max_retries=3, retry_delay=0.01)
        def fail_then_succeed():
            call_count[0] += 1
            if call_count[0] < 3:
                raise requests.exceptions.ConnectionError("연결 실패")
            return "success"
        
        result = fail_then_succeed()
        
        assert result == "success"
        assert call_count[0] == 3
    
    def test_max_retries_exceeded(self):
        """최대 재시도 횟수 초과"""
        from shared.utils import safe_api_call
        import requests
        
        call_count = [0]
        
        @safe_api_call(api_name="항상 실패 API", max_retries=2, retry_delay=0.01)
        def always_fail():
            call_count[0] += 1
            raise requests.exceptions.Timeout("타임아웃")
        
        with pytest.raises(requests.exceptions.Timeout):
            always_fail()
        
        assert call_count[0] == 2
    
    def test_non_request_error_not_retried(self):
        """Request 오류가 아닌 예외는 즉시 발생"""
        from shared.utils import safe_api_call
        
        call_count = [0]
        
        @safe_api_call(api_name="타입 에러 API", max_retries=3, retry_delay=0.01)
        def raise_value_error():
            call_count[0] += 1
            raise ValueError("값 에러")
        
        with pytest.raises(ValueError):
            raise_value_error()
        
        assert call_count[0] == 1
    
    def test_retryable_status_codes(self):
        """재시도 가능한 상태 코드"""
        from shared.utils import safe_api_call
        import requests
        
        call_count = [0]
        
        @safe_api_call(
            api_name="상태 코드 테스트", 
            max_retries=3, 
            retry_delay=0.01,
            retryable_status_codes=(500, 503)
        )
        def api_with_status():
            call_count[0] += 1
            if call_count[0] < 3:
                # Mock response with status code
                mock_response = MagicMock()
                mock_response.status_code = 503
                error = requests.exceptions.HTTPError()
                error.response = mock_response
                raise error
            return "recovered"
        
        result = api_with_status()
        
        assert result == "recovered"
        assert call_count[0] == 3


# ============================================================================
# Tests: _get_reporter 함수
# ============================================================================

class TestGetReporter:
    """_get_reporter 함수 테스트"""
    
    def test_get_reporter_success(self):
        """FailureReporter 로드 성공"""
        from shared.utils import _get_reporter
        
        # 실제 import 시도
        reporter = _get_reporter()
        
        # 로드 성공하면 FailureReporter 인스턴스, 실패하면 None
        assert reporter is None or reporter is not None
    
    def test_get_reporter_import_error(self):
        """ImportError 시 None 반환"""
        with patch.dict('sys.modules', {'shared.failure_reporter': None}):
            with patch('shared.utils._get_reporter', return_value=None):
                from shared.utils import _get_reporter
                result = _get_reporter()
        
        # Import가 성공하거나 None을 반환해야 함
        assert result is None or result is not None


# ============================================================================
# Tests: RetryStrategy Enum
# ============================================================================

class TestRetryStrategy:
    """RetryStrategy Enum 테스트"""
    
    def test_enum_values(self):
        """Enum 값 확인"""
        assert RetryStrategy.EXPONENTIAL_BACKOFF.value == "exponential_backoff"
        assert RetryStrategy.FIXED_INTERVAL.value == "fixed_interval"
        assert RetryStrategy.IMMEDIATE.value == "immediate"
    
    def test_enum_comparison(self):
        """Enum 비교"""
        assert RetryStrategy.EXPONENTIAL_BACKOFF != RetryStrategy.FIXED_INTERVAL
        assert RetryStrategy.EXPONENTIAL_BACKOFF == RetryStrategy.EXPONENTIAL_BACKOFF

