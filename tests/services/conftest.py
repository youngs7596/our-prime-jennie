# tests/services/conftest.py
# 서비스 테스트용 공통 fixtures
# 작업 LLM: Claude Opus 4

"""
서비스 테스트에서 사용할 공통 fixtures를 정의합니다.

Fixtures:
---------
- mock_kis: KIS API 클라이언트 Mock
- mock_config: ConfigManager Mock
- mock_telegram: TelegramBot Mock
- mock_db_session: DB 세션 Mock
"""

import pytest
from unittest.mock import MagicMock, create_autospec, patch
import sys
import os

# 프로젝트 루트를 sys.path에 추가
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    # sys.path.insert(0, PROJECT_ROOT)
    pass


class MockConfig:
    """
    테스트용 ConfigManager Mock 클래스
    
    실제 ConfigManager와 동일한 인터페이스를 제공합니다.
    """
    def __init__(self, overrides: dict = None):
        self._values = {
            # Trading
            'TRADING_MODE': 'MOCK',
            'MAX_BUY_COUNT_PER_DAY': 5,
            'MAX_PORTFOLIO_SIZE': 10,
            
            # Diversification
            'MAX_SECTOR_PCT': 30.0,
            'MAX_POSITION_VALUE_PCT': 10.0,
            
            # Position Sizing
            'RISK_PER_TRADE_PCT': 2.0,
            'ATR_MULTIPLIER': 2.0,
            'MIN_QUANTITY': 1,
            'MAX_QUANTITY': 1000,
            'CASH_KEEP_PCT': 10.0,
            'ATR_PERIOD': 14,
            
            # Recon
            'RECON_POSITION_MULT': 0.3,
            'RECON_STOP_LOSS_PCT': -0.025,
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
    
    def get_bool(self, key, default=False):
        val = self._values.get(key)
        if val is None:
            return default
        if isinstance(val, bool):
            return val
        return str(val).lower() in ('true', '1', 'yes')
    
    def set(self, key, value, persist_to_db=False):
        """설정값 업데이트 (apply_preset_to_config 호출용)"""
        self._values[key] = value


@pytest.fixture
def mock_config():
    """ConfigManager Mock fixture"""
    return MockConfig()


@pytest.fixture
def mock_config_factory():
    """커스텀 설정을 가진 ConfigManager 생성 팩토리"""
    def _create_config(overrides: dict = None):
        return MockConfig(overrides)
    return _create_config


@pytest.fixture
def mock_kis():
    """
    KIS API 클라이언트 Mock fixture
    
    주요 메서드:
    - get_cash_balance(): 현금 잔고 조회
    - get_stock_snapshot(): 실시간 시세 조회
    - place_buy_order(): 매수 주문
    - place_sell_order(): 매도 주문
    """
    kis = MagicMock()
    kis.get_cash_balance.return_value = 10_000_000  # 1천만원
    kis.get_stock_snapshot.return_value = {'price': 70000}
    kis.place_buy_order.return_value = 'BUY_ORDER_123456'
    kis.place_sell_order.return_value = 'SELL_ORDER_123456'
    return kis


@pytest.fixture
def mock_kis_strict():
    """KIS Gateway Client Strict Mock (create_autospec 기반)

    존재하지 않는 메서드 호출 → AttributeError
    잘못된 인자 수 → TypeError
    """
    from shared.kis.gateway_client import KISGatewayClient

    mock = create_autospec(KISGatewayClient, instance=True)
    mock.get_cash_balance.return_value = 10_000_000
    mock.get_stock_snapshot.return_value = {'price': 70000}
    mock.place_buy_order.return_value = 'ORDER123456'
    mock.place_sell_order.return_value = 'SELL_ORDER_123456'
    mock.cancel_order.return_value = True
    mock.check_market_open.return_value = True
    mock.get_account_balance.return_value = {'total': 50_000_000, 'cash': 10_000_000}
    return mock


@pytest.fixture
def mock_telegram():
    """
    TelegramBot Mock fixture
    
    send_message() 호출 시 항상 True 반환
    """
    bot = MagicMock()
    bot.send_message.return_value = True
    return bot


@pytest.fixture
def mock_db_session():
    """DB 세션 Mock fixture"""
    session = MagicMock()
    session.commit = MagicMock()
    session.rollback = MagicMock()
    session.close = MagicMock()
    return session


@pytest.fixture
def sample_candidate():
    """샘플 매수 후보 데이터"""
    return {
        'stock_code': '005930',
        'stock_name': '삼성전자',
        'current_price': 70000,
        'llm_score': 80,
        'llm_reason': '반도체 업황 개선 기대',
        'is_tradable': True,
        'trade_tier': 'TIER1',
        'factor_score': 75.5,
        'buy_signal_type': 'VOLUME_BREAKOUT',
        'key_metrics_dict': {}
    }


@pytest.fixture
def sample_candidates():
    """샘플 매수 후보 리스트"""
    return [
        {
            'stock_code': '005930',
            'stock_name': '삼성전자',
            'current_price': 70000,
            'llm_score': 85,
            'is_tradable': True,
            'trade_tier': 'TIER1'
        },
        {
            'stock_code': '000660',
            'stock_name': 'SK하이닉스',
            'current_price': 180000,
            'llm_score': 78,
            'is_tradable': True,
            'trade_tier': 'TIER1'
        },
        {
            'stock_code': '035720',
            'stock_name': '카카오',
            'current_price': 45000,
            'llm_score': 65,
            'is_tradable': False,
            'trade_tier': 'TIER2'
        }
    ]


@pytest.fixture
def sample_holding():
    """샘플 보유 종목 데이터"""
    from datetime import datetime, timezone, timedelta
    return {
        'id': 1,
        'code': '005930',
        'stock_code': '005930',
        'name': '삼성전자',
        'stock_name': '삼성전자',
        'quantity': 10,
        'avg_price': 70000,
        'buy_price': 70000,
        'current_price': 75000,
        'created_at': datetime.now(timezone.utc) - timedelta(days=5),
        'stop_loss_price': 66500,
        'high_price': 76000
    }


@pytest.fixture
def sample_portfolio():
    """샘플 포트폴리오 데이터"""
    from datetime import datetime, timezone, timedelta
    return [
        {
            'id': 1,
            'code': '005930',
            'name': '삼성전자',
            'quantity': 10,
            'avg_price': 70000,
            'current_price': 72000,
            'created_at': datetime.now(timezone.utc) - timedelta(days=10)
        },
        {
            'id': 2,
            'code': '000660',
            'name': 'SK하이닉스',
            'quantity': 5,
            'avg_price': 175000,
            'current_price': 180000,
            'created_at': datetime.now(timezone.utc) - timedelta(days=3)
        }
    ]


@pytest.fixture
def mock_database():
    """shared.database 모듈 Mock"""
    db = MagicMock()
    db.get_market_regime_cache.return_value = None
    db.get_daily_prices.return_value = None
    db.get_rag_context_with_validation.return_value = ("뉴스 없음", False, None)
    db.execute_trade_and_log.return_value = True
    db.update_performance_stats.return_value = True
    return db


@pytest.fixture
def mock_repository():
    """shared.db.repository 모듈 Mock"""
    repo = MagicMock()
    repo.get_active_portfolio.return_value = []
    repo.get_today_buy_count.return_value = 0
    repo.was_traded_recently.return_value = False
    return repo


@pytest.fixture
def mock_redis():
    """Redis Mock fixture"""
    redis = MagicMock()
    redis.set.return_value = True
    redis.get.return_value = None
    redis.delete.return_value = True
    return redis

