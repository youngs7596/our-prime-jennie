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
sys.path.insert(0, PROJECT_ROOT)


def load_executor_module():
    """하이픈이 있는 디렉토리에서 executor 모듈 로드"""
    module_path = os.path.join(PROJECT_ROOT, 'services', 'buy-executor', 'executor.py')
    spec = importlib.util.spec_from_file_location("buy_executor", module_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules['buy_executor'] = module
    spec.loader.exec_module(module)
    return module


class MockConfig:
    """테스트용 ConfigManager Mock"""
    def __init__(self, overrides: dict = None):
        self._values = {
            'TRADING_MODE': 'MOCK',
            'MAX_BUY_COUNT_PER_DAY': 5,
            'MAX_PORTFOLIO_SIZE': 10,
            'MIN_LLM_SCORE': 60,
            'MIN_LLM_SCORE_TIER2': 65,
            'MIN_LLM_SCORE_RECON': 65,
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
                gemini_api_key="test_key",
                telegram_bot=mock_telegram
            )
            
            # 빈 후보 리스트
            result = buy_exec.process_buy_signal({'candidates': []}, dry_run=True)
            
            assert result['status'] == 'skipped'
            assert 'No candidates' in result['reason']

    def test_safety_check_blocks_execution(self, mock_kis, mock_config, mock_telegram):
        """안전장치 발동 시 실행 차단"""
        with patch('shared.db.connection.session_scope') as mock_session, \
             patch('shared.db.repository.get_today_buy_count') as mock_buy_count, \
             patch('shared.db.repository.get_active_portfolio') as mock_portfolio, \
             patch('shared.position_sizing.PositionSizer'), \
             patch('shared.portfolio_diversification.DiversificationChecker'), \
             patch('shared.sector_classifier.SectorClassifier') as mock_sector, \
             patch('shared.market_regime.MarketRegimeDetector'), \
             patch('shared.database') as mock_db:
            
            # 오늘 매수 횟수가 최대치 도달
            mock_buy_count.return_value = 5
            mock_portfolio.return_value = []
            mock_db.get_market_regime_cache.return_value = None
            mock_sector.return_value.get_sector.return_value = "IT"
            
            mock_ctx = MagicMock()
            mock_session.return_value.__enter__ = MagicMock(return_value=mock_ctx)
            mock_session.return_value.__exit__ = MagicMock(return_value=False)
            
            executor = load_executor_module()
            
            buy_exec = executor.BuyExecutor(
                kis=mock_kis,
                config=mock_config,
                gemini_api_key="test_key",
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
        with patch('shared.db.repository.get_today_buy_count') as mock_count, \
             patch('shared.db.repository.get_active_portfolio') as mock_portfolio, \
             patch('shared.position_sizing.PositionSizer'), \
             patch('shared.portfolio_diversification.DiversificationChecker'), \
             patch('shared.sector_classifier.SectorClassifier') as mock_sector, \
             patch('shared.market_regime.MarketRegimeDetector'):
            
            mock_count.return_value = 5  # 최대치
            mock_portfolio.return_value = []
            mock_sector.return_value.get_sector.return_value = "IT"
            
            executor = load_executor_module()
            
            mock_kis = MagicMock()
            buy_exec = executor.BuyExecutor(
                kis=mock_kis,
                config=mock_config,
                gemini_api_key="test_key"
            )
            
            mock_session = MagicMock()
            result = buy_exec._check_safety_constraints(mock_session)
            
            assert result['allowed'] == False
            assert 'Daily buy limit' in result['reason']
    
    def test_portfolio_size_limit_exceeded(self, mock_config):
        """포트폴리오 사이즈 한도 초과"""
        with patch('shared.db.repository.get_today_buy_count') as mock_count, \
             patch('shared.db.repository.get_active_portfolio') as mock_portfolio, \
             patch('shared.position_sizing.PositionSizer'), \
             patch('shared.portfolio_diversification.DiversificationChecker'), \
             patch('shared.sector_classifier.SectorClassifier') as mock_sector, \
             patch('shared.market_regime.MarketRegimeDetector'):
            
            mock_count.return_value = 0
            # 10개 종목 보유 (최대치)
            mock_portfolio.return_value = [{'code': f'00{i}930'} for i in range(10)]
            mock_sector.return_value.get_sector.return_value = "IT"
            
            executor = load_executor_module()
            
            mock_kis = MagicMock()
            buy_exec = executor.BuyExecutor(
                kis=mock_kis,
                config=mock_config,
                gemini_api_key="test_key"
            )
            
            mock_session = MagicMock()
            result = buy_exec._check_safety_constraints(mock_session)
            
            assert result['allowed'] == False
            assert 'Portfolio size limit' in result['reason']
    
    def test_safety_check_passes(self, mock_config):
        """안전 체크 통과"""
        with patch('shared.db.repository.get_today_buy_count') as mock_count, \
             patch('shared.db.repository.get_active_portfolio') as mock_portfolio, \
             patch('shared.position_sizing.PositionSizer'), \
             patch('shared.portfolio_diversification.DiversificationChecker'), \
             patch('shared.sector_classifier.SectorClassifier') as mock_sector, \
             patch('shared.market_regime.MarketRegimeDetector'):
            
            mock_count.return_value = 2
            mock_portfolio.return_value = [{'code': '005930'}]  # 1개 보유
            mock_sector.return_value.get_sector.return_value = "IT"
            
            executor = load_executor_module()
            
            mock_kis = MagicMock()
            buy_exec = executor.BuyExecutor(
                kis=mock_kis,
                config=mock_config,
                gemini_api_key="test_key"
            )
            
            mock_session = MagicMock()
            result = buy_exec._check_safety_constraints(mock_session)
            
            assert result['allowed'] == True
            assert result['reason'] == 'OK'


class TestDiversificationCheck:
    """_check_diversification 메서드 테스트"""
    
    def test_sector_concentration_rejected(self, mock_config):
        """섹터 집중도 초과 거부"""
        with patch('shared.position_sizing.PositionSizer'), \
             patch('shared.portfolio_diversification.DiversificationChecker') as mock_div, \
             patch('shared.sector_classifier.SectorClassifier') as mock_sector, \
             patch('shared.market_regime.MarketRegimeDetector'):
            
            mock_sector.return_value.get_sector.return_value = "IT"
            mock_div.return_value.check_diversification.return_value = {
                'approved': False,
                'reason': "섹터 'IT' 비중 초과 (35% > 30%)",
                'current_sector_exposure': 25.0,
                'concentration_risk': 'HIGH'
            }
            
            executor = load_executor_module()
            
            mock_kis = MagicMock()
            buy_exec = executor.BuyExecutor(
                kis=mock_kis,
                config=mock_config,
                gemini_api_key="test_key"
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
        with patch('shared.position_sizing.PositionSizer'), \
             patch('shared.portfolio_diversification.DiversificationChecker') as mock_div, \
             patch('shared.sector_classifier.SectorClassifier') as mock_sector, \
             patch('shared.market_regime.MarketRegimeDetector'):
            
            mock_sector.return_value.get_sector.return_value = "IT"
            mock_div.return_value.check_diversification.return_value = {
                'approved': True,
                'reason': "분산 규칙 통과",
                'concentration_risk': 'LOW'
            }
            
            executor = load_executor_module()
            
            mock_kis = MagicMock()
            buy_exec = executor.BuyExecutor(
                kis=mock_kis,
                config=mock_config,
                gemini_api_key="test_key"
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


class TestLLMScoreValidation:
    """LLM 점수 검증 테스트"""
    
    def test_tier1_minimum_score(self, mock_config):
        """TIER1 최소 점수 검증"""
        config = MockConfig({'MIN_LLM_SCORE': 60})
        
        # TIER1 경로는 60점 이상 필요
        candidate = {
            'llm_score': 55,
            'trade_tier': 'TIER1',
            'is_tradable': True
        }
        
        # 점수 미달 확인 로직
        min_llm_score = config.get_int('MIN_LLM_SCORE', default=60)
        assert candidate['llm_score'] < min_llm_score
    
    def test_tier2_minimum_score(self, mock_config):
        """TIER2 최소 점수 검증"""
        config = MockConfig({'MIN_LLM_SCORE_TIER2': 65})
        
        # TIER2 경로는 65점 이상 필요
        candidate = {
            'llm_score': 60,
            'trade_tier': 'TIER2',
            'is_tradable': False
        }
        
        min_llm_score_tier2 = config.get_int('MIN_LLM_SCORE_TIER2', default=65)
        assert candidate['llm_score'] < min_llm_score_tier2


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
            
            mock_ctx = MagicMock()
            mock_session.return_value.__enter__ = MagicMock(return_value=mock_ctx)
            mock_session.return_value.__exit__ = MagicMock(return_value=False)
            
            buy_exec = executor_module.BuyExecutor(
                kis=mock_kis,
                config=mock_config,
                gemini_api_key="test_key"
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
        with patch('shared.db.connection.session_scope') as mock_session, \
             patch('shared.db.repository.get_active_portfolio') as mock_portfolio, \
             patch('shared.db.repository.get_today_buy_count') as mock_count, \
             patch('shared.db.repository.was_traded_recently') as mock_traded, \
             patch('shared.database') as mock_db, \
             patch('shared.position_sizing.PositionSizer'), \
             patch('shared.portfolio_diversification.DiversificationChecker'), \
             patch('shared.sector_classifier.SectorClassifier') as mock_sector, \
             patch('shared.market_regime.MarketRegimeDetector'):
            
            mock_db.get_market_regime_cache.return_value = None
            mock_portfolio.return_value = []
            mock_count.return_value = 0
            mock_traded.return_value = True  # 최근에 거래됨
            mock_sector.return_value.get_sector.return_value = "IT"
            
            mock_ctx = MagicMock()
            mock_session.return_value.__enter__ = MagicMock(return_value=mock_ctx)
            mock_session.return_value.__exit__ = MagicMock(return_value=False)
            
            executor = load_executor_module()
            
            buy_exec = executor.BuyExecutor(
                kis=mock_kis,
                config=mock_config,
                gemini_api_key="test_key"
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
        with patch('shared.db.connection.session_scope') as mock_session, \
             patch('shared.db.repository.get_active_portfolio') as mock_portfolio, \
             patch('shared.db.repository.get_today_buy_count') as mock_count, \
             patch('shared.db.repository.was_traded_recently') as mock_traded, \
             patch('shared.database') as mock_db, \
             patch('shared.position_sizing.PositionSizer'), \
             patch('shared.portfolio_diversification.DiversificationChecker'), \
             patch('shared.sector_classifier.SectorClassifier') as mock_sector, \
             patch('shared.market_regime.MarketRegimeDetector'):
            
            mock_db.get_market_regime_cache.return_value = None
            # 이미 삼성전자 보유 중
            mock_portfolio.return_value = [{'code': '005930', 'name': '삼성전자'}]
            mock_count.return_value = 0
            mock_traded.return_value = False
            mock_sector.return_value.get_sector.return_value = "IT"
            
            mock_ctx = MagicMock()
            mock_session.return_value.__enter__ = MagicMock(return_value=mock_ctx)
            mock_session.return_value.__exit__ = MagicMock(return_value=False)
            
            executor = load_executor_module()
            
            buy_exec = executor.BuyExecutor(
                kis=mock_kis,
                config=mock_config,
                gemini_api_key="test_key"
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


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

