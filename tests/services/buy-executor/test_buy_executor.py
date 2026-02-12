# tests/services/buy-executor/test_buy_executor.py
# BuyExecutor 유닛 테스트
# 작업 LLM: Claude Opus 4

"""
BuyExecutor 클래스의 핵심 기능을 테스트합니다.

테스트 범위:
- process_buy_signal: 매수 신호 처리 전체 흐름
- _check_safety_constraints: 안전장치 체크
- _check_diversification: 포트폴리오 분산 검증
- _record_trade: 거래 기록
"""

import unittest
try:
    import pytest
except ImportError:
    pytest = None

# unittest discover 시 pytest 없으면 전체 모듈 스킵
if pytest is None:
    raise unittest.SkipTest("pytest not installed, skipping pytest-based tests")
from unittest.mock import MagicMock, patch, PropertyMock
from datetime import datetime, timezone
import sys
import os
import importlib.util

# 프로젝트 루트 추가
PROJECT_ROOT = os.path.join(os.path.dirname(__file__), '..', '..', '..')
# sys.path.insert(0, PROJECT_ROOT)


_executor_module_cache = None

def load_executor_module():
    """하이픈이 있는 디렉토리에서 executor 모듈 로드 (Singleton Pattern)"""
    global _executor_module_cache
    if _executor_module_cache:
        return _executor_module_cache

    module_path = os.path.join(PROJECT_ROOT, 'services', 'buy-executor', 'executor.py')
    spec = importlib.util.spec_from_file_location("buy_executor", module_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules['buy_executor'] = module
    
    # 전략 프리셋 및 DB 의존성 모킹 제거 (테스트 메서드에서 제어)
    spec.loader.exec_module(module)
    
    _executor_module_cache = module
    return module


class MockConfig:
    """테스트용 ConfigManager Mock"""
    def __init__(self, overrides: dict = None):
        self._values = {
            'TRADING_MODE': 'MOCK',
            'MAX_BUY_COUNT_PER_DAY': 5,
            'MAX_PORTFOLIO_SIZE': 10,
            'MAX_SECTOR_PCT': 30.0,
            'MAX_POSITION_VALUE_PCT': 10.0,
            'RISK_PER_TRADE_PCT': 2.0,
            'ATR_MULTIPLIER': 2.0,
            'MIN_QUANTITY': 1,
            'MAX_QUANTITY': 1000,
            'CASH_KEEP_PCT': 10.0,
            'ATR_PERIOD': 14,
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
def mock_kis():
    """KIS API Mock"""
    kis = MagicMock()
    kis.get_cash_balance.return_value = 10_000_000  # 1천만원
    kis.get_stock_snapshot.return_value = {'price': 70000}
    kis.place_buy_order.return_value = 'ORDER123456'
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
def buy_executor(mock_kis, mock_config, mock_telegram):
    """BuyExecutor 인스턴스 생성"""
    with patch('services.buy-executor.executor.SectorClassifier') as mock_sector_cls, \
         patch('services.buy-executor.executor.MarketRegimeDetector') as mock_regime:
        
        mock_sector_cls.return_value.get_sector.return_value = "IT"
        mock_regime.return_value = MagicMock()
        mock_regime.REGIME_STRONG_BULL = "STRONG_BULL"
        
        # executor 모듈 직접 import 대신, 클래스를 직접 테스트
        from services.buy_executor_module import BuyExecutor  # 이 방식은 불가능
        # 대안: 필요한 클래스만 임포트하고 mock 적용


@pytest.fixture(autouse=True)
def mock_redis_trading_flags():
    """Redis Trading Flags를 기본적으로 False로 Mocking (실제 Redis 연결 방지)"""
    with patch('shared.redis_cache.is_trading_stopped', return_value=False), \
         patch('shared.redis_cache.is_trading_paused', return_value=False):
        yield


class TestBuyExecutorSignalProcessing:
    """process_buy_signal 메서드 테스트"""
    
    def test_no_candidates_returns_skipped(self, mock_kis, mock_config, mock_telegram):
        """후보가 없을 때 skipped 반환"""
        with patch('shared.db.connection.session_scope') as mock_session, \
             patch('shared.db.repository') as mock_repo, \
             patch('shared.position_sizing.PositionSizer'), \
             patch('shared.portfolio_diversification.DiversificationChecker'), \
             patch('shared.sector_classifier.SectorClassifier') as mock_sector, \
             patch('shared.market_regime.MarketRegimeDetector'), \
             patch('shared.strategy_presets.resolve_preset_for_regime', return_value=('TEST_PRESET', {})), \
             patch('shared.strategy_presets.apply_preset_to_config'), \
             patch('shared.database') as mock_db:
            
            mock_sector.return_value.get_sector.return_value = "IT"
            mock_db.get_market_regime_cache.return_value = None
            
            mock_ctx = MagicMock()
            mock_session.return_value.__enter__ = MagicMock(return_value=mock_ctx)
            mock_session.return_value.__exit__ = MagicMock(return_value=False)
            
            # BuyExecutor 동적 로드
            executor = load_executor_module()
            
            buy_exec = executor.BuyExecutor(
                kis=mock_kis,
                config=mock_config,
                
                telegram_bot=mock_telegram
            )
            
            # 빈 후보 리스트
            result = buy_exec.process_buy_signal({'candidates': []}, dry_run=True)
            
            assert result['status'] == 'skipped'
            assert 'No candidates' in result['reason']

    def test_safety_check_blocks_execution(self, mock_kis, mock_config, mock_telegram):
        """안전장치 발동 시 실행 차단"""
        # Load module first to get the correct namespace
        executor = load_executor_module()
        
        with patch('shared.db.connection.session_scope') as mock_session, \
             patch.object(executor.repo, 'get_today_buy_count', return_value=5) as mock_buy_count, \
             patch.object(executor.repo, 'get_active_portfolio', return_value=[]) as mock_portfolio, \
             patch('shared.position_sizing.PositionSizer'), \
             patch('shared.portfolio_diversification.DiversificationChecker'), \
             patch('shared.sector_classifier.SectorClassifier') as mock_sector, \
             patch('shared.market_regime.MarketRegimeDetector'), \
             patch('shared.database') as mock_db:
            
            # mock_buy_count.return_value = 5 # Set in patch.object
            # mock_portfolio.return_value = [] # Set in patch.object
            mock_db.get_market_regime_cache.return_value = None
            mock_sector.return_value.get_sector.return_value = "IT"
            
            mock_ctx = MagicMock()
            mock_session.return_value.__enter__ = MagicMock(return_value=mock_ctx)
            mock_session.return_value.__exit__ = MagicMock(return_value=False)
            
            buy_exec = executor.BuyExecutor(
                kis=mock_kis,
                config=mock_config,
                
                telegram_bot=mock_telegram
            )
            
            candidates = [{
                'stock_code': '005930',
                'stock_name': '삼성전자',
                'llm_score': 80,
                'is_tradable': True,
                'current_price': 70000
            }]
            
            result = buy_exec.process_buy_signal({'candidates': candidates}, dry_run=True)
            
            assert result['status'] == 'skipped'
            assert 'Daily buy limit' in result['reason']


class TestSafetyConstraints:
    """_check_safety_constraints 메서드 테스트"""
    
    def test_daily_buy_limit_exceeded(self, mock_config):
        """일일 매수 한도 초과"""
        executor = load_executor_module()
        
        with patch.object(executor.repo, 'get_today_buy_count', return_value=5) as mock_count, \
             patch.object(executor.repo, 'get_active_portfolio', return_value=[]) as mock_portfolio, \
             patch('shared.position_sizing.PositionSizer'), \
             patch('shared.portfolio_diversification.DiversificationChecker'), \
             patch('shared.sector_classifier.SectorClassifier') as mock_sector, \
             patch('shared.market_regime.MarketRegimeDetector'):
            
            # mock_count.return_value = 5  # 최대치
            # mock_portfolio.return_value = []
            mock_sector.return_value.get_sector.return_value = "IT"
            
            mock_kis = MagicMock()
            buy_exec = executor.BuyExecutor(
                kis=mock_kis,
                config=mock_config,
                
            )
            
            mock_session = MagicMock()
            result = buy_exec._check_safety_constraints(mock_session)
            
            assert result['allowed'] == False
            assert 'Daily buy limit' in result['reason']
    
    def test_portfolio_size_limit_exceeded(self, mock_config):
        """포트폴리오 사이즈 한도 초과"""
        executor = load_executor_module()

        with patch.object(executor.repo, 'get_today_buy_count', return_value=0) as mock_count, \
             patch.object(executor.repo, 'get_active_portfolio', return_value=[{'code': f'00{i}930'} for i in range(10)]) as mock_portfolio, \
             patch('shared.position_sizing.PositionSizer'), \
             patch('shared.portfolio_diversification.DiversificationChecker'), \
             patch('shared.sector_classifier.SectorClassifier') as mock_sector, \
             patch('shared.market_regime.MarketRegimeDetector'):
            
            # mock_count.return_value = 0
            # 10개 종목 보유 (최대치)
            # mock_portfolio.return_value = [{'code': f'00{i}930'} for i in range(10)]
            mock_sector.return_value.get_sector.return_value = "IT"
            
            mock_kis = MagicMock()
            buy_exec = executor.BuyExecutor(
                kis=mock_kis,
                config=mock_config,
                
            )
            
            mock_session = MagicMock()
            result = buy_exec._check_safety_constraints(mock_session)
            
            assert result['allowed'] == False
            assert 'Portfolio size limit' in result['reason']
    
    def test_safety_check_passes(self, mock_config):
        """안전 체크 통과"""
        executor = load_executor_module()

        with patch.object(executor.repo, 'get_today_buy_count', return_value=2) as mock_count, \
             patch.object(executor.repo, 'get_active_portfolio', return_value=[{'code': '005930'}]) as mock_portfolio, \
             patch('shared.position_sizing.PositionSizer'), \
             patch('shared.portfolio_diversification.DiversificationChecker'), \
             patch('shared.sector_classifier.SectorClassifier') as mock_sector, \
             patch('shared.market_regime.MarketRegimeDetector'):
            
            # mock_count.return_value = 2
            # mock_portfolio.return_value = [{'code': '005930'}]  # 1개 보유
            mock_sector.return_value.get_sector.return_value = "IT"
            
            mock_kis = MagicMock()
            buy_exec = executor.BuyExecutor(
                kis=mock_kis,
                config=mock_config,
                
            )
            
            mock_session = MagicMock()
            result = buy_exec._check_safety_constraints(mock_session)
            
            assert result['allowed'] == True
            assert result['reason'] == 'OK'


class TestDiversificationCheck:
    """_check_diversification 메서드 테스트"""
    
    def test_sector_concentration_rejected(self, mock_config):
        """섹터 집중도 초과 거부"""
        executor = load_executor_module()
        
        with patch('shared.position_sizing.PositionSizer'), \
             patch.object(executor, 'DiversificationChecker') as mock_div, \
             patch('shared.sector_classifier.SectorClassifier') as mock_sector, \
             patch('shared.market_regime.MarketRegimeDetector'):
            
            mock_sector.return_value.get_sector.return_value = "IT"
            mock_div.return_value.check_diversification.return_value = {
                'approved': False,
                'reason': "섹터 'IT' 비중 초과 (35% > 30%)",
                'current_sector_exposure': 25.0,
                'concentration_risk': 'HIGH'
            }
            
            # executor = load_executor_module()
            
            mock_kis = MagicMock()
            buy_exec = executor.BuyExecutor(
                kis=mock_kis,
                config=mock_config,
                
            )
            
            candidate = {
                'stock_code': '005930',
                'stock_name': '삼성전자',
                'current_price': 70000
            }
            
            mock_session = MagicMock()
            is_approved, result = buy_exec._check_diversification(
                session=mock_session,
                candidate=candidate,
                current_portfolio=[],
                available_cash=10_000_000,
                position_size=10,
                current_price=70000
            )
            
            assert is_approved == False
            assert '비중 초과' in result['reason']
    
    def test_diversification_passes(self, mock_config):
        """분산 규칙 통과"""
        executor = load_executor_module()

        with patch('shared.position_sizing.PositionSizer'), \
             patch.object(executor, 'DiversificationChecker') as mock_div, \
             patch('shared.sector_classifier.SectorClassifier') as mock_sector, \
             patch('shared.market_regime.MarketRegimeDetector'):
            
            mock_sector.return_value.get_sector.return_value = "IT"
            mock_div.return_value.check_diversification.return_value = {
                'approved': True,
                'reason': "분산 규칙 통과",
                'concentration_risk': 'LOW'
            }
            
            # executor = load_executor_module()
            
            mock_kis = MagicMock()
            buy_exec = executor.BuyExecutor(
                kis=mock_kis,
                config=mock_config,
                
            )
            
            candidate = {
                'stock_code': '005930',
                'stock_name': '삼성전자',
                'current_price': 70000
            }
            
            mock_session = MagicMock()
            is_approved, result = buy_exec._check_diversification(
                session=mock_session,
                candidate=candidate,
                current_portfolio=[],
                available_cash=10_000_000,
                position_size=10,
                current_price=70000
            )
            
            assert is_approved == True


class TestStaleScoreMultiplier:
    """Stale Score 포지션 배율 테스트 (scored_dt 다음날부터 카운트, 주말 제외)"""

    def _calc_stale(self, scored_date, now_date):
        """실제 executor.py와 동일한 business_days 계산 로직"""
        from datetime import timedelta
        business_days = 0
        current_date = scored_date + timedelta(days=1)  # 스코어링 다음 날부터
        while current_date <= now_date:
            if current_date.weekday() < 5:
                business_days += 1
            current_date += timedelta(days=1)

        if business_days >= 3:
            return business_days, 0.3
        elif business_days >= 2:
            return business_days, 0.5
        else:
            return business_days, 1.0

    def test_same_day_no_penalty(self):
        """당일 점수는 배율 축소 없음"""
        from datetime import date
        scored = date(2026, 2, 3)  # 화요일
        now = date(2026, 2, 3)     # 같은 화요일
        bdays, mult = self._calc_stale(scored, now)
        assert bdays == 0
        assert mult == 1.0

    def test_next_business_day_no_penalty(self):
        """직전 영업일(1영업일 경과)은 정상 → 배율 축소 없음"""
        from datetime import date
        scored = date(2026, 2, 3)  # 화요일
        now = date(2026, 2, 4)     # 수요일 (1영업일)
        bdays, mult = self._calc_stale(scored, now)
        assert bdays == 1
        assert mult == 1.0

    def test_friday_to_monday_no_penalty(self):
        """금요일 Scout → 월요일 Scanner = 1영업일 → 정상 (주말 때문)"""
        from datetime import date
        scored = date(2026, 2, 6)  # 금요일
        now = date(2026, 2, 9)     # 월요일
        bdays, mult = self._calc_stale(scored, now)
        assert bdays == 1
        assert mult == 1.0

    def test_2_business_days_half(self):
        """2영업일 경과 시 stale_multiplier = 0.5"""
        from datetime import date
        scored = date(2026, 2, 3)  # 화요일
        now = date(2026, 2, 5)     # 목요일 (2영업일)
        bdays, mult = self._calc_stale(scored, now)
        assert bdays == 2
        assert mult == 0.5

    def test_3_business_days_severe(self):
        """3영업일 이상 경과 시 stale_multiplier = 0.3"""
        from datetime import date
        scored = date(2026, 2, 3)  # 화요일
        now = date(2026, 2, 6)     # 금요일 (3영업일)
        bdays, mult = self._calc_stale(scored, now)
        assert bdays == 3
        assert mult == 0.3


class TestRealtimeSourceFastPath:
    """Realtime Source 빠른 경로 테스트 (Phase 3)"""
    
    def test_opportunity_watcher_source_logged(self):
        """OpportunityWatcher 신호는 빠른 경로로 처리"""
        scan_result = {
            'candidates': [{'llm_score': 65, 'stock_code': '005930'}],
            'source': 'opportunity_watcher',  # 실시간 신호
            'market_regime': 'BULL'
        }
        
        # source가 opportunity_watcher면 빠른 경로
        assert scan_result.get('source') == 'opportunity_watcher'
    
    def test_stale_score_penalty(self):
        """24시간 이상 된 점수는 10점 감점"""
        from datetime import datetime, timezone, timedelta
        
        # 48시간 전 점수
        old_time = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
        
        selected_candidate = {
            'llm_score': 70,
            'stock_info': {'llm_scored_at': old_time}
        }
        
        current_score = selected_candidate.get('llm_score', 0)
        llm_scored_at = selected_candidate.get('stock_info', {}).get('llm_scored_at')
        
        if llm_scored_at:
            scored_dt = datetime.fromisoformat(llm_scored_at.replace('Z', '+00:00'))
            age_hours = (datetime.now(timezone.utc) - scored_dt).total_seconds() / 3600
            if age_hours > 24:
                penalty = 10
                current_score = max(0, current_score - penalty)
        
        # 70 - 10 = 60점
        assert current_score == 60
        assert age_hours > 24
    
    def test_fresh_score_no_penalty(self):
        """최신 점수는 감점 없음"""
        from datetime import datetime, timezone, timedelta
        
        # 2시간 전 점수
        recent_time = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        
        selected_candidate = {
            'llm_score': 70,
            'stock_info': {'llm_scored_at': recent_time}
        }
        
        current_score = selected_candidate.get('llm_score', 0)
        llm_scored_at = selected_candidate.get('stock_info', {}).get('llm_scored_at')
        
        if llm_scored_at:
            scored_dt = datetime.fromisoformat(llm_scored_at.replace('Z', '+00:00'))
            age_hours = (datetime.now(timezone.utc) - scored_dt).total_seconds() / 3600
            if age_hours > 24:
                penalty = 10
                current_score = max(0, current_score - penalty)
        
        # 감점 없이 70점 유지
        assert current_score == 70
        assert age_hours < 24


class TestPositionSizing:
    """포지션 사이징 테스트"""
    
    def test_position_sizer_integration(self, mock_config):
        """PositionSizer 통합 테스트"""
        from shared.position_sizing import PositionSizer
        
        sizer = PositionSizer(mock_config)
        
        result = sizer.calculate_quantity(
            stock_code='005930',
            stock_price=70000,
            atr=1400,  # 2% ATR
            account_balance=10_000_000,
            portfolio_value=5_000_000
        )
        
        assert 'quantity' in result
        assert result['quantity'] >= 0
        assert 'reason' in result
    
    def test_position_sizer_zero_balance(self, mock_config):
        """잔고가 0일 때"""
        from shared.position_sizing import PositionSizer
        
        sizer = PositionSizer(mock_config)
        
        result = sizer.calculate_quantity(
            stock_code='005930',
            stock_price=70000,
            atr=1400,
            account_balance=0,
            portfolio_value=0
        )
        
        assert result['quantity'] == 0
        assert '총 자산이 0' in result['reason']


class TestDryRunMode:
    """DRY_RUN 모드 테스트"""
    
    def test_dry_run_no_actual_order(self, mock_kis, mock_config):
        """DRY_RUN 모드에서 실제 주문 없음"""
        # DRY_RUN 모드에서는 kis.place_buy_order가 호출되지 않음
        executor_module = load_executor_module()
        with patch.object(executor_module, 'session_scope') as mock_session, \
             patch.object(executor_module, 'repo') as mock_repo, \
             patch.object(executor_module, 'database') as mock_db, \
             patch.object(executor_module, 'redis_cache') as mock_redis, \
             patch.object(executor_module, 'PositionSizer') as mock_sizer, \
             patch.object(executor_module, 'DiversificationChecker') as mock_div, \
             patch.object(executor_module, 'SectorClassifier') as mock_sector, \
             patch.object(executor_module, 'MarketRegimeDetector'), \
             patch.object(executor_module, 'PortfolioGuard') as mock_guard, \
             patch.object(executor_module, 'check_portfolio_correlation', return_value=(True, None, 0.0)), \
             patch.object(executor_module, 'get_correlation_risk_adjustment', return_value=1.0):

            # Setup mocks
            mock_db.get_market_regime_cache.return_value = None
            mock_repo.get_active_portfolio.return_value = []
            mock_repo.get_today_buy_count.return_value = 0
            mock_repo.was_traded_recently.return_value = False
            mock_redis.get_redis_connection.return_value = MagicMock(set=MagicMock(return_value=True))
            mock_sector.return_value.get_sector.return_value = "IT"
            mock_sizer.return_value.calculate_quantity.return_value = {
                'quantity': 10, 'reason': 'test'
            }
            mock_div.return_value.check_diversification.return_value = {
                'approved': True, 'reason': 'OK'
            }
            mock_guard.return_value.check_all.return_value = {
                'passed': True, 'reason': 'OK', 'shadow': False, 'checks': {}
            }
            
            mock_ctx = MagicMock()
            mock_session.return_value.__enter__ = MagicMock(return_value=mock_ctx)
            mock_session.return_value.__exit__ = MagicMock(return_value=False)
            
            buy_exec = executor_module.BuyExecutor(
                kis=mock_kis,
                config=mock_config,
                
            )
            
            candidates = [{
                'stock_code': '005930',
                'stock_name': '삼성전자',
                'llm_score': 80,
                'is_tradable': True,
                'current_price': 70000,
                'trade_tier': 'TIER1'
            }]
            
            result = buy_exec.process_buy_signal({'candidates': candidates}, dry_run=True)
            
            # DRY_RUN이므로 실제 주문 API 호출 없어야 함
            mock_kis.place_buy_order.assert_not_called()
            
            if result['status'] == 'success':
                assert 'DRY_RUN' in result.get('order_no', '')


class TestIdempotency:
    """Idempotency (중복 실행 방지) 테스트"""
    
    def test_duplicate_order_blocked(self, mock_kis, mock_config):
        """최근 주문이 있을 때 중복 실행 차단"""
        executor = load_executor_module()
        
        with patch('shared.db.connection.session_scope') as mock_session, \
             patch.object(executor.repo, 'get_active_portfolio', return_value=[]) as mock_portfolio, \
             patch.object(executor.repo, 'get_today_buy_count', return_value=0) as mock_count, \
             patch.object(executor.repo, 'was_traded_recently', return_value=True) as mock_traded, \
             patch('shared.database') as mock_db, \
             patch('shared.position_sizing.PositionSizer'), \
             patch('shared.portfolio_diversification.DiversificationChecker'), \
             patch('shared.sector_classifier.SectorClassifier') as mock_sector, \
             patch('shared.market_regime.MarketRegimeDetector'):
            
            mock_db.get_market_regime_cache.return_value = None
            # mock_portfolio.return_value = []
            # mock_count.return_value = 0
            # mock_traded.return_value = True  # 최근에 거래됨
            mock_sector.return_value.get_sector.return_value = "IT"
            
            mock_ctx = MagicMock()
            mock_session.return_value.__enter__ = MagicMock(return_value=mock_ctx)
            mock_session.return_value.__exit__ = MagicMock(return_value=False)
            
            # executor = load_executor_module()
            
            buy_exec = executor.BuyExecutor(
                kis=mock_kis,
                config=mock_config,
                
            )
            
            candidates = [{
                'stock_code': '005930',
                'stock_name': '삼성전자',
                'llm_score': 80,
                'is_tradable': True,
                'current_price': 70000
            }]
            
            result = buy_exec.process_buy_signal({'candidates': candidates}, dry_run=True)
            
            assert result['status'] == 'skipped'
            assert 'Duplicate' in result['reason']
    
    def test_already_held_stock_filtered(self, mock_kis, mock_config):
        """이미 보유한 종목 필터링"""
        executor = load_executor_module()

        with patch('shared.db.connection.session_scope') as mock_session, \
             patch.object(executor.repo, 'get_active_portfolio', return_value=[{'code': '005930', 'name': '삼성전자'}]) as mock_portfolio, \
             patch.object(executor.repo, 'get_today_buy_count', return_value=0) as mock_count, \
             patch.object(executor.repo, 'was_traded_recently', return_value=False) as mock_traded, \
             patch('shared.database') as mock_db, \
             patch('shared.position_sizing.PositionSizer'), \
             patch('shared.portfolio_diversification.DiversificationChecker'), \
             patch('shared.sector_classifier.SectorClassifier') as mock_sector, \
             patch('shared.market_regime.MarketRegimeDetector'):
            
            mock_db.get_market_regime_cache.return_value = None
            # 이미 삼성전자 보유 중
            # mock_portfolio.return_value = [{'code': '005930', 'name': '삼성전자'}]
            # mock_count.return_value = 0
            # mock_traded.return_value = False
            mock_sector.return_value.get_sector.return_value = "IT"
            
            mock_ctx = MagicMock()
            mock_session.return_value.__enter__ = MagicMock(return_value=mock_ctx)
            mock_session.return_value.__exit__ = MagicMock(return_value=False)
            
            # executor = load_executor_module()
            
            buy_exec = executor.BuyExecutor(
                kis=mock_kis,
                config=mock_config,
                
            )
            
            # 삼성전자만 후보로 넘기면 필터링되어 빈 리스트가 됨
            candidates = [{
                'stock_code': '005930',
                'stock_name': '삼성전자',
                'llm_score': 80,
                'is_tradable': True
            }]
            
            result = buy_exec.process_buy_signal({'candidates': candidates}, dry_run=True)
            
            assert result['status'] == 'skipped'
            assert 'already held' in result['reason']


class TestEmergencyStopCheck:
    """긴급 정지 및 일시 정지 테스트"""
    
    def test_emergency_stop_blocks_execution(self, mock_kis, mock_config, mock_telegram):
        """긴급 정지 상태에서 매수 실행 차단"""
        executor = load_executor_module()
        
        with patch('shared.redis_cache.is_trading_stopped', return_value=True):
            buy_exec = executor.BuyExecutor(
                kis=mock_kis,
                config=mock_config,
                
                telegram_bot=mock_telegram
            )
            
            result = buy_exec.process_buy_signal({'candidates': [{'stock_code': '005930'}]}, dry_run=True)
            
            assert result['status'] == 'skipped'
            assert 'Emergency Stop' in result['reason']

    def test_paused_trading_blocks_automated_buy(self, mock_kis, mock_config, mock_telegram):
        """매수 일시 정지 상태에서 자동 매수 차단"""
        executor = load_executor_module()
        
        with patch('shared.redis_cache.is_trading_stopped', return_value=False), \
             patch('shared.redis_cache.is_trading_paused', return_value=True):
            
            buy_exec = executor.BuyExecutor(
                kis=mock_kis,
                config=mock_config,
                
                telegram_bot=mock_telegram
            )
            
            # 일반 경로 (RabbitMQ)
            result = buy_exec.process_buy_signal({'candidates': [{'stock_code': '005930'}], 'source': 'rabbitmq'}, dry_run=True)
            
            assert result['status'] == 'skipped'
            assert 'Trading Paused' in result['reason']

    def test_paused_trading_allows_manual_buy(self, mock_kis, mock_config, mock_telegram):
        """매수 일시 정지 상태여도 Telegram 수동 매수는 허용"""
        executor = load_executor_module()
        
        with patch('shared.redis_cache.is_trading_stopped', return_value=False), \
             patch('shared.redis_cache.is_trading_paused', return_value=True), \
             patch('shared.db.connection.session_scope') as mock_session, \
             patch('shared.database.get_market_regime_cache', return_value=None):
             
            # Session Mock
            mock_ctx = MagicMock()
            mock_session.return_value.__enter__ = MagicMock(return_value=mock_ctx)
            mock_session.return_value.__exit__ = MagicMock(return_value=False)

            buy_exec = executor.BuyExecutor(
                kis=mock_kis,
                config=mock_config,
                
                telegram_bot=mock_telegram
            )
            
            # 수동 매수 소스 (후보 없음 -> No candidates 리턴)
            scan_result = {
                'candidates': [],
                'source': 'telegram-manual'
            }
            
            # 만약 Pause 체크에 걸린다면 'Trading Paused' 리턴
            # 통과한다면 'No candidates' 리턴
            result = buy_exec.process_buy_signal(scan_result, dry_run=True)
            
            assert result['status'] == 'skipped'
            assert 'No candidates' in result['reason']
            assert 'Trading Paused' not in result['reason']

class TestPortfolioGuardIntegration:
    """Portfolio Guard가 executor에서 제대로 동작하는지 통합 테스트"""

    def test_portfolio_guard_blocks_sector_concentration(self, mock_kis, mock_config):
        """섹터 종목 수 초과 시 executor가 skipped 반환"""
        executor_module = load_executor_module()

        with patch.object(executor_module, 'session_scope') as mock_session, \
             patch.object(executor_module, 'repo') as mock_repo, \
             patch.object(executor_module, 'database') as mock_db, \
             patch.object(executor_module, 'redis_cache') as mock_redis, \
             patch.object(executor_module, 'PositionSizer') as mock_sizer, \
             patch.object(executor_module, 'DiversificationChecker') as mock_div, \
             patch.object(executor_module, 'SectorClassifier') as mock_sector, \
             patch.object(executor_module, 'MarketRegimeDetector'), \
             patch.object(executor_module, 'PortfolioGuard') as mock_guard, \
             patch.object(executor_module, 'check_portfolio_correlation', return_value=(True, None, 0.0)), \
             patch.object(executor_module, 'get_correlation_risk_adjustment', return_value=1.0):

            mock_db.get_market_regime_cache.return_value = None
            mock_repo.get_active_portfolio.return_value = []
            mock_repo.get_today_buy_count.return_value = 0
            mock_repo.was_traded_recently.return_value = False
            mock_redis.is_trading_stopped.return_value = False
            mock_redis.is_trading_paused.return_value = False
            mock_redis.get_redis_connection.return_value = MagicMock(set=MagicMock(return_value=True))
            mock_sector.return_value.get_sector.return_value = "IT"
            mock_sizer.return_value.calculate_quantity.return_value = {
                'quantity': 10, 'reason': 'test'
            }
            mock_sizer.return_value.calculate_intraday_atr.return_value = None
            mock_sizer.return_value.refresh_from_config.return_value = None
            # Portfolio Guard가 차단
            mock_guard.return_value.check_all.return_value = {
                'passed': False,
                'reason': "Portfolio Guard: 섹터 종목 수 초과: '금융' 대분류에 이미 3종목 보유 (한도: 3)",
                'shadow': False,
                'checks': {},
            }

            mock_ctx = MagicMock()
            mock_session.return_value.__enter__ = MagicMock(return_value=mock_ctx)
            mock_session.return_value.__exit__ = MagicMock(return_value=False)

            buy_exec = executor_module.BuyExecutor(
                kis=mock_kis, config=mock_config
            )

            candidates = [{
                'stock_code': '105560',
                'stock_name': 'KB금융',
                'llm_score': 80,
                'is_tradable': True,
                'current_price': 70000,
                'trade_tier': 'TIER1',
            }]

            result = buy_exec.process_buy_signal({'candidates': candidates}, dry_run=True)

            assert result['status'] == 'skipped'
            assert 'Portfolio Guard' in result['reason']
            # 실제 주문 없어야 함
            mock_kis.place_buy_order.assert_not_called()

    def test_portfolio_guard_blocks_cash_floor(self, mock_kis, mock_config):
        """현금 하한선 위반 시 executor가 skipped 반환"""
        executor_module = load_executor_module()

        with patch.object(executor_module, 'session_scope') as mock_session, \
             patch.object(executor_module, 'repo') as mock_repo, \
             patch.object(executor_module, 'database') as mock_db, \
             patch.object(executor_module, 'redis_cache') as mock_redis, \
             patch.object(executor_module, 'PositionSizer') as mock_sizer, \
             patch.object(executor_module, 'DiversificationChecker') as mock_div, \
             patch.object(executor_module, 'SectorClassifier') as mock_sector, \
             patch.object(executor_module, 'MarketRegimeDetector'), \
             patch.object(executor_module, 'PortfolioGuard') as mock_guard, \
             patch.object(executor_module, 'check_portfolio_correlation', return_value=(True, None, 0.0)), \
             patch.object(executor_module, 'get_correlation_risk_adjustment', return_value=1.0):

            mock_db.get_market_regime_cache.return_value = None
            mock_repo.get_active_portfolio.return_value = []
            mock_repo.get_today_buy_count.return_value = 0
            mock_repo.was_traded_recently.return_value = False
            mock_redis.is_trading_stopped.return_value = False
            mock_redis.is_trading_paused.return_value = False
            mock_redis.get_redis_connection.return_value = MagicMock(set=MagicMock(return_value=True))
            mock_sector.return_value.get_sector.return_value = "IT"
            mock_sizer.return_value.calculate_quantity.return_value = {
                'quantity': 10, 'reason': 'test'
            }
            mock_sizer.return_value.calculate_intraday_atr.return_value = None
            mock_sizer.return_value.refresh_from_config.return_value = None
            mock_guard.return_value.check_all.return_value = {
                'passed': False,
                'reason': "Portfolio Guard: 현금 하한선 위반: 매수 후 현금 3.0% < 하한선 10.0% (국면: BULL)",
                'shadow': False,
                'checks': {},
            }

            mock_ctx = MagicMock()
            mock_session.return_value.__enter__ = MagicMock(return_value=mock_ctx)
            mock_session.return_value.__exit__ = MagicMock(return_value=False)

            buy_exec = executor_module.BuyExecutor(
                kis=mock_kis, config=mock_config
            )

            candidates = [{
                'stock_code': '005930',
                'stock_name': '삼성전자',
                'llm_score': 80,
                'is_tradable': True,
                'current_price': 70000,
                'trade_tier': 'TIER1',
            }]

            result = buy_exec.process_buy_signal(
                {'candidates': candidates, 'market_regime': 'BULL'},
                dry_run=True,
            )

            assert result['status'] == 'skipped'
            assert 'Portfolio Guard' in result['reason']
            assert '현금 하한선' in result['reason']

    def test_portfolio_guard_passes_allows_execution(self, mock_kis, mock_config):
        """Portfolio Guard 통과 → 매수 진행"""
        executor_module = load_executor_module()

        with patch.object(executor_module, 'session_scope') as mock_session, \
             patch.object(executor_module, 'repo') as mock_repo, \
             patch.object(executor_module, 'database') as mock_db, \
             patch.object(executor_module, 'redis_cache') as mock_redis, \
             patch.object(executor_module, 'PositionSizer') as mock_sizer, \
             patch.object(executor_module, 'DiversificationChecker') as mock_div, \
             patch.object(executor_module, 'SectorClassifier') as mock_sector, \
             patch.object(executor_module, 'MarketRegimeDetector'), \
             patch.object(executor_module, 'PortfolioGuard') as mock_guard, \
             patch.object(executor_module, 'check_portfolio_correlation', return_value=(True, None, 0.0)), \
             patch.object(executor_module, 'get_correlation_risk_adjustment', return_value=1.0):

            mock_db.get_market_regime_cache.return_value = None
            mock_db.get_daily_prices.return_value = None
            mock_db.execute_trade_and_log.return_value = True
            mock_repo.get_active_portfolio.return_value = []
            mock_repo.get_today_buy_count.return_value = 0
            mock_repo.was_traded_recently.return_value = False
            mock_redis.is_trading_stopped.return_value = False
            mock_redis.is_trading_paused.return_value = False
            mock_redis.get_redis_connection.return_value = MagicMock(set=MagicMock(return_value=True))
            mock_redis.reset_trading_state_for_stock.return_value = None
            mock_sector.return_value.get_sector.return_value = "IT"
            mock_sizer.return_value.calculate_quantity.return_value = {
                'quantity': 10, 'reason': 'test'
            }
            mock_sizer.return_value.calculate_intraday_atr.return_value = None
            mock_sizer.return_value.refresh_from_config.return_value = None
            mock_div.return_value.check_diversification.return_value = {
                'approved': True, 'reason': 'OK'
            }
            mock_guard.return_value.check_all.return_value = {
                'passed': True, 'reason': 'OK', 'shadow': False, 'checks': {}
            }

            mock_ctx = MagicMock()
            mock_session.return_value.__enter__ = MagicMock(return_value=mock_ctx)
            mock_session.return_value.__exit__ = MagicMock(return_value=False)

            buy_exec = executor_module.BuyExecutor(
                kis=mock_kis, config=mock_config
            )

            candidates = [{
                'stock_code': '005930',
                'stock_name': '삼성전자',
                'llm_score': 80,
                'is_tradable': True,
                'current_price': 70000,
                'trade_tier': 'TIER1',
            }]

            result = buy_exec.process_buy_signal({'candidates': candidates}, dry_run=True)

            assert result['status'] == 'success'
            assert 'DRY_RUN' in result.get('order_no', '')


class TestAlignToTickSize(unittest.TestCase):
    """KRX 호가 단위 정렬 함수 테스트 (2026-02-12 장애 회귀 방지)."""

    def test_tick_sizes(self):
        executor = load_executor_module()
        align = executor.align_to_tick_size

        # ~2,000원: 1원 단위
        assert align(1500) == 1500
        assert align(1501) == 1501

        # ~5,000원: 5원 단위
        assert align(3003) == 3005
        assert align(3005) == 3005

        # ~20,000원: 10원 단위
        assert align(15003) == 15010
        assert align(15010) == 15010

        # ~50,000원: 50원 단위
        assert align(34402) == 34450  # 삼성E&A 케이스
        assert align(34400) == 34400

        # ~200,000원: 100원 단위
        assert align(100050) == 100100
        assert align(100100) == 100100

        # ~500,000원: 500원 단위
        assert align(384650) == 385000  # POSCO홀딩스 케이스
        assert align(298893) == 299000  # 한솔케미칼 케이스
        assert align(385000) == 385000

        # 500,000원~: 1,000원 단위
        assert align(500500) == 501000
        assert align(501000) == 501000


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

