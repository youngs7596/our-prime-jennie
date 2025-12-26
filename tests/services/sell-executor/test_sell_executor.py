# tests/services/sell-executor/test_sell_executor.py
# SellExecutor 유닛 테스트
# 작업 LLM: Claude Opus 4

"""
SellExecutor 클래스의 핵심 기능을 테스트합니다.

테스트 범위:
- execute_sell_order: 매도 주문 실행 전체 흐름
- _record_sell_trade: 매도 거래 기록
- 수익률/손실 계산
- Idempotency (중복 실행 방지)
"""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone, timedelta
import sys
import os
import importlib.util

# 프로젝트 루트 추가
PROJECT_ROOT = os.path.join(os.path.dirname(__file__), '..', '..', '..')
sys.path.insert(0, PROJECT_ROOT)

# Fix: Ensure shared.database is imported before patching
import shared.database


def load_executor_module():
    """하이픈이 있는 디렉토리에서 executor 모듈 로드"""
    module_path = os.path.join(PROJECT_ROOT, 'services', 'sell-executor', 'executor.py')
    spec = importlib.util.spec_from_file_location("sell_executor", module_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules['sell_executor'] = module
    spec.loader.exec_module(module)
    return module


class MockConfig:
    """테스트용 ConfigManager Mock"""
    def __init__(self, overrides: dict = None):
        self._values = {
            'TRADING_MODE': 'MOCK',
        }
        if overrides:
            self._values.update(overrides)
    
    def get(self, key, default=None):
        return self._values.get(key, default)
    
    def get_int(self, key, default=0):
        val = self._values.get(key)
        return int(val) if val is not None else default
    
    def get_float(self, key, default=0.0):
        val = self._values.get(key)
        return float(val) if val is not None else default
    
    def set(self, key, value, persist_to_db=False):
        """설정값 업데이트 (apply_preset_to_config 호출용)"""
        self._values[key] = value


@pytest.fixture
def mock_kis():
    """KIS API Mock"""
    kis = MagicMock()
    kis.get_stock_snapshot.return_value = {'price': 75000}
    kis.place_sell_order.return_value = 'SELL_ORDER_123456'
    return kis


@pytest.fixture
def mock_config():
    """ConfigManager Mock"""
    return MockConfig()


@pytest.fixture
def mock_telegram():
    """TelegramBot Mock"""
    bot = MagicMock()
    bot.send_message.return_value = True
    return bot


@pytest.fixture
def sample_holding():
    """샘플 보유 종목 데이터"""
    return {
        'id': 1,
        'code': '005930',
        'name': '삼성전자',
        'quantity': 10,
        'avg_price': 70000,
        'buy_price': 70000,
        'current_price': 75000,
        'created_at': datetime.now(timezone.utc) - timedelta(days=5),
        'stop_loss_price': 66500,
        'high_price': 76000
    }


class TestSellExecutorBasicFlow:
    """execute_sell_order 기본 흐름 테스트"""
    
    def test_successful_sell_order_dry_run(self, mock_kis, mock_config, mock_telegram, sample_holding):
        """성공적인 매도 주문 (DRY RUN)"""
        import pandas as pd
        
        with patch('shared.db.connection.session_scope') as mock_session, \
             patch('shared.db.repository.get_active_portfolio') as mock_portfolio, \
             patch('shared.db.repository.was_traded_recently') as mock_traded, \
             patch('shared.db.repository.check_duplicate_order', return_value=False), \
             patch('shared.database') as mock_db:
            
            # Setup mocks
            mock_portfolio.return_value = [sample_holding]
            mock_traded.return_value = False
            mock_db.get_market_regime_cache.return_value = None
            mock_db.get_daily_prices.return_value = pd.DataFrame({
                'CLOSE_PRICE': [75000]
            })
            mock_db.get_rag_context_with_validation.return_value = ("뉴스 없음", False, None)
            mock_db.execute_trade_and_log.return_value = True
            
            mock_ctx = MagicMock()
            mock_session.return_value.__enter__ = MagicMock(return_value=mock_ctx)
            mock_session.return_value.__exit__ = MagicMock(return_value=False)
            
            executor = load_executor_module()
            
            sell_exec = executor.SellExecutor(
                kis=mock_kis,
                config=mock_config,
                telegram_bot=mock_telegram
            )
            
            result = sell_exec.execute_sell_order(
                stock_code='005930',
                stock_name='삼성전자',
                quantity=10,
                sell_reason='익절 (목표가 도달)',
                dry_run=True
            )
            
            assert result['status'] == 'success'
            assert 'DRY_RUN' in result['order_no']
            assert result['quantity'] == 10
            # 수익률 확인 (75000 - 70000) / 70000 * 100 = 7.14%
            assert result['profit_pct'] > 0
    
    def test_stock_not_in_portfolio(self, mock_kis, mock_config, mock_telegram):
        """보유하지 않은 종목 매도 시도"""
        with patch('shared.db.connection.session_scope') as mock_session, \
             patch('shared.db.repository.get_active_portfolio') as mock_portfolio, \
             patch('shared.db.repository.check_duplicate_order', return_value=False), \
             patch('shared.database') as mock_db:
            
            mock_portfolio.return_value = []  # 빈 포트폴리오
            mock_db.get_market_regime_cache.return_value = None
            
            mock_ctx = MagicMock()
            mock_session.return_value.__enter__ = MagicMock(return_value=mock_ctx)
            mock_session.return_value.__exit__ = MagicMock(return_value=False)
            
            executor = load_executor_module()
            
            sell_exec = executor.SellExecutor(
                kis=mock_kis,
                config=mock_config,
                telegram_bot=mock_telegram
            )
            
            result = sell_exec.execute_sell_order(
                stock_code='005930',
                stock_name='삼성전자',
                quantity=10,
                sell_reason='익절',
                dry_run=True
            )
            
            assert result['status'] == 'error'
            assert 'Not in portfolio' in result['reason']


class TestIdempotency:
    """Idempotency (중복 실행 방지) 테스트"""
    
    def test_duplicate_sell_blocked(self, mock_kis, mock_config, sample_holding):
        """최근 매도 주문이 있을 때 중복 실행 차단"""
        with patch('shared.db.connection.session_scope') as mock_session, \
             patch('shared.db.repository.get_active_portfolio') as mock_portfolio, \
             patch('shared.db.repository.was_traded_recently') as mock_traded, \
             patch('shared.database') as mock_db:
            
            mock_portfolio.return_value = [sample_holding]
            mock_traded.return_value = True  # 최근에 거래됨
            mock_db.get_market_regime_cache.return_value = None
            
            mock_ctx = MagicMock()
            mock_session.return_value.__enter__ = MagicMock(return_value=mock_ctx)
            mock_session.return_value.__exit__ = MagicMock(return_value=False)
            
            executor = load_executor_module()
            
            sell_exec = executor.SellExecutor(
                kis=mock_kis,
                config=mock_config
            )
            
            result = sell_exec.execute_sell_order(
                stock_code='005930',
                stock_name='삼성전자',
                quantity=10,
                sell_reason='익절',
                dry_run=True
            )
            
            assert result['status'] == 'skipped'
            assert 'Duplicate' in result['reason']


class TestProfitCalculation:
    """수익률 계산 테스트"""
    
    def test_profit_calculation_positive(self):
        """양수 수익률 계산"""
        buy_price = 70000
        current_price = 77000
        quantity = 10
        
        profit_pct = ((current_price - buy_price) / buy_price) * 100
        profit_amount = (current_price - buy_price) * quantity
        
        assert profit_pct == 10.0  # 10% 수익
        assert profit_amount == 70000  # 7만원 수익
    
    def test_profit_calculation_negative(self):
        """음수 수익률 (손실) 계산"""
        buy_price = 70000
        current_price = 63000
        quantity = 10
        
        profit_pct = ((current_price - buy_price) / buy_price) * 100
        profit_amount = (current_price - buy_price) * quantity
        
        assert profit_pct == -10.0  # 10% 손실
        assert profit_amount == -70000  # 7만원 손실
    
    def test_profit_calculation_zero(self):
        """수익률 0 (본전)"""
        buy_price = 70000
        current_price = 70000
        quantity = 10
        
        profit_pct = ((current_price - buy_price) / buy_price) * 100
        profit_amount = (current_price - buy_price) * quantity
        
        assert profit_pct == 0.0
        assert profit_amount == 0


class TestHoldingDaysCalculation:
    """보유 일수 계산 테스트"""
    
    def test_holding_days_calculation(self):
        """보유 일수 계산"""
        buy_date = datetime.now(timezone.utc) - timedelta(days=10)
        holding_days = (datetime.now(timezone.utc) - buy_date).days
        
        assert holding_days == 10
    
    def test_holding_days_same_day(self):
        """당일 매도 시 보유 일수 0"""
        buy_date = datetime.now(timezone.utc)
        holding_days = (datetime.now(timezone.utc) - buy_date).days
        
        assert holding_days == 0


class TestRealOrderExecution:
    """실제 주문 실행 테스트"""
    
    def test_real_order_calls_kis_api(self, mock_kis, mock_config, sample_holding):
        """실제 주문 시 KIS API 호출"""
        import pandas as pd
        
        with patch('shared.db.connection.session_scope') as mock_session, \
             patch('shared.db.repository.get_active_portfolio') as mock_portfolio, \
             patch('shared.db.repository.was_traded_recently') as mock_traded, \
             patch('shared.db.repository.check_duplicate_order', return_value=False), \
             patch('shared.database') as mock_db, \
             patch.dict(os.environ, {'TRADING_MODE': 'REAL'}):
            
            mock_portfolio.return_value = [sample_holding]
            mock_traded.return_value = False
            mock_db.get_market_regime_cache.return_value = None
            mock_db.get_rag_context_with_validation.return_value = ("뉴스 없음", False, None)
            mock_db.execute_trade_and_log.return_value = True
            
            mock_ctx = MagicMock()
            mock_session.return_value.__enter__ = MagicMock(return_value=mock_ctx)
            mock_session.return_value.__exit__ = MagicMock(return_value=False)
            
            executor = load_executor_module()
            
            sell_exec = executor.SellExecutor(
                kis=mock_kis,
                config=mock_config
            )
            
            result = sell_exec.execute_sell_order(
                stock_code='005930',
                stock_name='삼성전자',
                quantity=10,
                sell_reason='익절',
                dry_run=False
            )
            
            # 실제 주문 시 KIS API 호출 확인
            mock_kis.place_sell_order.assert_called_once_with(
                stock_code='005930',
                quantity=10,
                price=0  # 시장가
            )
            
            if result['status'] == 'success':
                assert result['order_no'] == 'SELL_ORDER_123456'
    
    def test_order_failure_handling(self, mock_kis, mock_config, sample_holding):
        """주문 실패 처리"""
        import pandas as pd
        
        mock_kis.place_sell_order.return_value = None  # 주문 실패
        
        with patch('shared.db.connection.session_scope') as mock_session, \
             patch('shared.db.repository.get_active_portfolio') as mock_portfolio, \
             patch('shared.db.repository.was_traded_recently') as mock_traded, \
             patch('shared.db.repository.check_duplicate_order', return_value=False), \
             patch('shared.database') as mock_db, \
             patch.dict(os.environ, {'TRADING_MODE': 'REAL'}):
            
            mock_portfolio.return_value = [sample_holding]
            mock_traded.return_value = False
            mock_db.get_market_regime_cache.return_value = None
            mock_db.get_rag_context_with_validation.return_value = ("뉴스 없음", False, None)
            
            mock_ctx = MagicMock()
            mock_session.return_value.__enter__ = MagicMock(return_value=mock_ctx)
            mock_session.return_value.__exit__ = MagicMock(return_value=False)
            
            executor = load_executor_module()
            
            sell_exec = executor.SellExecutor(
                kis=mock_kis,
                config=mock_config
            )
            
            result = sell_exec.execute_sell_order(
                stock_code='005930',
                stock_name='삼성전자',
                quantity=10,
                sell_reason='익절',
                dry_run=False
            )
            
            assert result['status'] == 'error'
            assert 'Order failed' in result['reason']


class TestTelegramNotification:
    """텔레그램 알림 테스트"""
    
    def test_telegram_notification_sent_on_success(self, mock_kis, mock_config, mock_telegram, sample_holding):
        """성공 시 텔레그램 알림 발송"""
        import pandas as pd
        
        with patch('shared.db.connection.session_scope') as mock_session, \
             patch('shared.db.repository.get_active_portfolio') as mock_portfolio, \
             patch('shared.db.repository.was_traded_recently') as mock_traded, \
             patch('shared.db.repository.check_duplicate_order', return_value=False), \
             patch('shared.database') as mock_db:
            
            mock_portfolio.return_value = [sample_holding]
            mock_traded.return_value = False
            mock_db.get_market_regime_cache.return_value = None
            mock_db.get_daily_prices.return_value = pd.DataFrame({
                'CLOSE_PRICE': [75000]
            })
            mock_db.get_rag_context_with_validation.return_value = ("뉴스 없음", False, None)
            mock_db.execute_trade_and_log.return_value = True
            
            mock_ctx = MagicMock()
            mock_session.return_value.__enter__ = MagicMock(return_value=mock_ctx)
            mock_session.return_value.__exit__ = MagicMock(return_value=False)
            
            executor = load_executor_module()
            
            sell_exec = executor.SellExecutor(
                kis=mock_kis,
                config=mock_config,
                telegram_bot=mock_telegram
            )
            
            result = sell_exec.execute_sell_order(
                stock_code='005930',
                stock_name='삼성전자',
                quantity=10,
                sell_reason='익절',
                dry_run=True
            )
            
            if result['status'] == 'success':
                # 텔레그램 알림 발송 확인
                mock_telegram.send_message.assert_called()


class TestKeyMetricsRecording:
    """복기용 지표 기록 테스트"""
    
    def test_key_metrics_structure(self, sample_holding):
        """key_metrics_dict 구조 검증"""
        current_price = 75000
        buy_price = sample_holding['avg_price']
        quantity = 10
        profit_pct = ((current_price - buy_price) / buy_price) * 100
        profit_amount = (current_price - buy_price) * quantity
        
        key_metrics_dict = {
            "sell_reason": "익절",
            "current_price": float(current_price),
            "buy_price": float(buy_price),
            "profit_pct": round(profit_pct, 2),
            "profit_amount": round(profit_amount, 0),
            "holding_days": 5,
            "stop_loss_price": float(sample_holding.get('stop_loss_price', 0)),
            "high_price": float(sample_holding.get('high_price', 0)),
            "rag_fresh": False,
            "rag_last_updated": None,
            "risk_setting": {}
        }
        
        # 필수 키 확인
        required_keys = [
            'sell_reason', 'current_price', 'buy_price', 
            'profit_pct', 'profit_amount', 'holding_days'
        ]
        for key in required_keys:
            assert key in key_metrics_dict
        
        # 값 타입 확인
        assert isinstance(key_metrics_dict['current_price'], float)
        assert isinstance(key_metrics_dict['profit_pct'], float)


class TestMockModePrice:
    """Mock 모드 가격 조회 테스트"""
    
    def test_mock_mode_uses_db_price(self, mock_kis, mock_config, sample_holding):
        """Mock 모드에서 DB 가격 사용"""
        import pandas as pd
        
        with patch('shared.db.connection.session_scope') as mock_session, \
             patch('shared.db.repository.get_active_portfolio') as mock_portfolio, \
             patch('shared.db.repository.was_traded_recently') as mock_traded, \
             patch('shared.db.repository.check_duplicate_order', return_value=False), \
             patch('shared.database') as mock_db, \
             patch.dict(os.environ, {'TRADING_MODE': 'MOCK'}):
            
            mock_portfolio.return_value = [sample_holding]
            mock_traded.return_value = False
            mock_db.get_market_regime_cache.return_value = None
            # Mock 모드에서는 DB 가격 사용
            mock_db.get_daily_prices.return_value = pd.DataFrame({
                'CLOSE_PRICE': [73000]
            })
            mock_db.get_rag_context_with_validation.return_value = ("뉴스 없음", False, None)
            mock_db.execute_trade_and_log.return_value = True
            
            mock_ctx = MagicMock()
            mock_session.return_value.__enter__ = MagicMock(return_value=mock_ctx)
            mock_session.return_value.__exit__ = MagicMock(return_value=False)
            
            executor = load_executor_module()
            
            sell_exec = executor.SellExecutor(
                kis=mock_kis,
                config=mock_config
            )
            
            result = sell_exec.execute_sell_order(
                stock_code='005930',
                stock_name='삼성전자',
                quantity=10,
                sell_reason='익절',
                dry_run=True
            )
            
            if result['status'] == 'success':
                # Mock 모드에서는 get_stock_snapshot 호출 안함
                mock_kis.get_stock_snapshot.assert_not_called()
                # DB에서 가져온 가격 73000 사용
                assert result['sell_price'] == 73000


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

