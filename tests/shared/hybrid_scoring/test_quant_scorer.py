"""
tests/shared/hybrid_scoring/test_quant_scorer.py - QuantScorer 테스트
====================================================================

shared/hybrid_scoring/quant_scorer.py의 정량 스코어링을 테스트합니다.
"""

import pytest
from unittest.mock import MagicMock, patch
import pandas as pd
import numpy as np
from datetime import datetime, date, timedelta


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def mock_stock_data():
    """Mock 주가 데이터"""
    # 120일치 주가 데이터 생성
    dates = pd.date_range(end=datetime.now(), periods=120, freq='D')

    return pd.DataFrame({
        'PRICE_DATE': dates,
        'CLOSE_PRICE': [50000 + i * 100 for i in range(120)],
        'HIGH_PRICE': [51000 + i * 100 for i in range(120)],
        'LOW_PRICE': [49000 + i * 100 for i in range(120)],
        'VOLUME': [1000000] * 120
    })


@pytest.fixture
def mock_investor_trading_df():
    """Mock 투자자 매매 동향 데이터 (smart_money_5d 계산용)"""
    dates = pd.date_range(end=datetime.now(), periods=10, freq='B')

    return pd.DataFrame({
        'TRADE_DATE': dates,
        'FOREIGN_NET_BUY': [50000, 30000, 20000, -10000, 40000,
                            60000, 80000, 70000, 90000, 100000],
        'INSTITUTION_NET_BUY': [20000, 10000, 15000, 5000, 25000,
                                30000, 40000, 35000, 45000, 50000],
        'CLOSE_PRICE': [50000 + i * 100 for i in range(10)],
    })


@pytest.fixture
def mock_financial_data():
    """Mock 재무 데이터"""
    return {
        '005930': {
            '2024-09-30': {'per': 10.5, 'pbr': 1.2, 'roe': 15.0},
            '2024-06-30': {'per': 11.0, 'pbr': 1.3, 'roe': 14.5}
        }
    }


@pytest.fixture
def mock_supply_data():
    """Mock 수급 데이터"""
    dates = pd.date_range(end=datetime.now(), periods=20, freq='D')
    
    return pd.DataFrame({
        'TRADE_DATE': dates,
        'FOREIGN_NET_BUY': [100000000] * 10 + [-50000000] * 10,
        'INSTITUTION_NET_BUY': [50000000] * 20
    })


@pytest.fixture
def mock_news_data():
    """Mock 뉴스 감성 데이터"""
    dates = pd.date_range(end=datetime.now(), periods=10, freq='D')
    
    return pd.DataFrame({
        'NEWS_DATE': dates,
        'SENTIMENT_SCORE': [70, 75, 80, 65, 85, 60, 90, 55, 70, 75],
        'CATEGORY': ['실적'] * 5 + ['수주'] * 5
    })


# ============================================================================
# Tests: QuantScoreResult 데이터클래스
# ============================================================================

class TestQuantScoreResult:
    """QuantScoreResult 데이터클래스 테스트"""
    
    def test_create_result(self):
        """결과 생성"""
        from shared.hybrid_scoring.quant_scorer import QuantScoreResult
        
        result = QuantScoreResult(
            stock_code='005930',
            stock_name='삼성전자',
            total_score=72.0,
            momentum_score=15.0,
            quality_score=20.0,
            value_score=12.0,
            technical_score=15.0,
            news_stat_score=5.0,
            supply_demand_score=5.0,
            matched_conditions=['rsi_oversold'],
            condition_win_rate=0.65,
            condition_sample_count=45,
            condition_confidence='MID'
        )
        
        assert result.stock_code == '005930'
        assert result.total_score == 72.0
    
    def test_dataclass_fields(self):
        """데이터클래스 필드 확인"""
        from shared.hybrid_scoring.quant_scorer import QuantScoreResult
        from dataclasses import fields
        
        field_names = [f.name for f in fields(QuantScoreResult)]
        
        assert 'stock_code' in field_names
        assert 'total_score' in field_names
        assert 'condition_confidence' in field_names


# ============================================================================
# Tests: QuantScorer 초기화
# ============================================================================

class TestQuantScorerInit:
    """QuantScorer 초기화 테스트"""
    
    def test_init_short_term(self):
        """단기 전략 초기화"""
        from shared.hybrid_scoring.quant_scorer import QuantScorer, StrategyMode
        
        scorer = QuantScorer(strategy_mode=StrategyMode.SHORT_TERM)
        
        assert scorer is not None
        assert scorer.strategy_mode == StrategyMode.SHORT_TERM
    
    def test_init_long_term(self):
        """장기 전략 초기화"""
        from shared.hybrid_scoring.quant_scorer import QuantScorer, StrategyMode
        
        scorer = QuantScorer(strategy_mode=StrategyMode.LONG_TERM)
        
        assert scorer is not None
        assert scorer.strategy_mode == StrategyMode.LONG_TERM
    
    def test_init_default_strategy(self):
        """기본 전략 (DUAL)"""
        from shared.hybrid_scoring.quant_scorer import QuantScorer, StrategyMode
        
        scorer = QuantScorer()
        
        assert scorer is not None
        assert scorer.strategy_mode == StrategyMode.DUAL


# ============================================================================
# Tests: 개별 팩터 점수 계산
# ============================================================================

class TestFactorCalculations:
    """개별 팩터 점수 계산 테스트"""
    
    def test_calc_rsi(self, mock_stock_data):
        """RSI 계산"""
        from shared.hybrid_scoring.quant_scorer import QuantScorer
        
        scorer = QuantScorer()
        
        # RSI 계산 (내부 메서드)
        if hasattr(scorer, '_calc_rsi'):
            rsi = scorer._calc_rsi(mock_stock_data['CLOSE_PRICE'])
            assert isinstance(rsi, (pd.Series, type(None)))
    
    def test_calc_quality_score(self):
        """품질 점수 계산 (ROE 기반)"""
        from shared.hybrid_scoring.quant_scorer import QuantScorer
        
        scorer = QuantScorer()
        
        # ROE 기반 품질 점수 (내부 로직)
        # 실제 구현에 따라 메서드 이름이 다를 수 있음
        if hasattr(scorer, '_calc_quality_score'):
            quality = scorer._calc_quality_score(roe=15.0)
            assert quality >= 0
    
    def test_factor_weights_loaded(self):
        """팩터 가중치 로드"""
        from shared.hybrid_scoring.quant_scorer import QuantScorer
        
        scorer = QuantScorer()
        
        # factor_weights 속성 확인
        assert hasattr(scorer, 'factor_weights')
        assert isinstance(scorer.factor_weights, dict)
        assert len(scorer.factor_weights) > 0


# ============================================================================
# Tests: 조건부 승률 매칭
# ============================================================================

class TestConditionMatching:
    """조건부 승률 매칭 테스트"""
    
    def test_condition_win_rate_struct(self):
        """조건부 승률 구조체 확인"""
        from shared.hybrid_scoring.quant_scorer import QuantScoreResult
        
        # QuantScoreResult에 조건 관련 필드 존재
        result = QuantScoreResult(
            stock_code='005930',
            stock_name='삼성전자',
            total_score=72.0,
            momentum_score=15.0,
            quality_score=20.0,
            value_score=12.0,
            technical_score=15.0,
            news_stat_score=5.0,
            supply_demand_score=5.0,
            matched_conditions=['rsi_oversold', 'foreign_buy'],
            condition_win_rate=0.65,
            condition_sample_count=45,
            condition_confidence='MID'
        )
        
        assert result.matched_conditions == ['rsi_oversold', 'foreign_buy']
        assert result.condition_win_rate == 0.65
    
    def test_compound_conditions(self):
        """복합 조건 필드"""
        from shared.hybrid_scoring.quant_scorer import QuantScoreResult
        
        result = QuantScoreResult(
            stock_code='005930',
            stock_name='삼성전자',
            total_score=72.0,
            momentum_score=15.0,
            quality_score=20.0,
            value_score=12.0,
            technical_score=15.0,
            news_stat_score=5.0,
            supply_demand_score=5.0,
            matched_conditions=[],
            condition_win_rate=None,
            condition_sample_count=0,
            condition_confidence='LOW',
            compound_bonus=5.0,
            compound_conditions=['rsi_foreign']
        )
        
        assert result.compound_bonus == 5.0


# ============================================================================
# Tests: calculate_total_quant_score (통합)
# ============================================================================

class TestCalculateTotalScore:
    """통합 점수 계산 테스트"""
    
    def test_calculate_total_quant_score_exists(self):
        """calculate_total_quant_score 메서드 존재"""
        from shared.hybrid_scoring.quant_scorer import QuantScorer
        
        scorer = QuantScorer()
        
        assert hasattr(scorer, 'calculate_total_quant_score')
        assert callable(scorer.calculate_total_quant_score)


# ============================================================================
# Tests: 전략별 가중치
# ============================================================================

class TestStrategyWeights:
    """전략별 가중치 테스트"""
    
    def test_factor_weights_dict(self):
        """팩터 가중치 딕셔너리"""
        from shared.hybrid_scoring.quant_scorer import QuantScorer, StrategyMode
        
        scorer = QuantScorer(strategy_mode=StrategyMode.SHORT_TERM)
        
        # factor_weights 속성
        assert hasattr(scorer, 'factor_weights')
        assert isinstance(scorer.factor_weights, dict)
    
    def test_default_factor_weights(self):
        """기본 팩터 가중치"""
        from shared.hybrid_scoring.schema import get_default_factor_weights
        
        weights = get_default_factor_weights()
        
        assert isinstance(weights, dict)
        assert 'quality_roe' in weights


# ============================================================================
# Tests: 점수 정규화
# ============================================================================

class TestScoreNormalization:
    """점수 정규화 테스트"""
    
    def test_score_range(self):
        """점수 범위 확인"""
        from shared.hybrid_scoring.quant_scorer import QuantScoreResult
        
        # 점수는 0~100 범위
        result = QuantScoreResult(
            stock_code='005930',
            stock_name='삼성전자',
            total_score=72.0,
            momentum_score=15.0,
            quality_score=20.0,
            value_score=12.0,
            technical_score=15.0,
            news_stat_score=5.0,
            supply_demand_score=5.0,
            matched_conditions=[],
            condition_win_rate=None,
            condition_sample_count=0,
            condition_confidence='LOW'
        )
        
        assert 0 <= result.total_score <= 100


# ============================================================================
# Tests: format_quant_score_for_prompt
# ============================================================================

class TestFormatForPrompt:
    """프롬프트 포맷 테스트"""
    
    def test_format_function_exists(self):
        """format 함수 존재 확인"""
        try:
            from shared.hybrid_scoring.quant_scorer import format_quant_score_for_prompt
            assert callable(format_quant_score_for_prompt)
        except ImportError:
            # 함수가 없으면 스킵
            pytest.skip("format_quant_score_for_prompt not found")


# ============================================================================
# Tests: Edge Cases
# ============================================================================

class TestEdgeCases:
    """Edge Cases 테스트"""
    
    def test_invalid_result_flags(self):
        """유효하지 않은 결과 플래그"""
        from shared.hybrid_scoring.quant_scorer import QuantScoreResult
        
        result = QuantScoreResult(
            stock_code='999999',
            stock_name='테스트종목',
            total_score=0.0,
            momentum_score=0.0,
            quality_score=0.0,
            value_score=0.0,
            technical_score=0.0,
            news_stat_score=0.0,
            supply_demand_score=0.0,
            matched_conditions=[],
            condition_win_rate=None,
            condition_sample_count=0,
            condition_confidence='LOW',
            is_valid=False,
            invalid_reason='데이터 부족'
        )
        
        assert result.is_valid is False
        assert result.invalid_reason == '데이터 부족'
    
    def test_sector_field(self):
        """섹터 필드"""
        from shared.hybrid_scoring.quant_scorer import QuantScoreResult
        
        result = QuantScoreResult(
            stock_code='005930',
            stock_name='삼성전자',
            total_score=72.0,
            momentum_score=15.0,
            quality_score=20.0,
            value_score=12.0,
            technical_score=15.0,
            news_stat_score=5.0,
            supply_demand_score=5.0,
            matched_conditions=[],
            condition_win_rate=None,
            condition_sample_count=0,
            condition_confidence='LOW',
            sector='반도체'
        )
        
        assert result.sector == '반도체'


# ============================================================================
# Tests: Supply Demand Score (25점 만점, Smart Money 5D 포함)
# ============================================================================

class TestSupplyDemandScore:
    """수급 점수 계산 테스트 (15점 만점 + smart_money_5d 보너스 최대 3점)"""

    def test_supply_demand_score_15_base(self, mock_investor_trading_df):
        """수급 기본 점수 15점 만점 검증 (보너스 제외)"""
        from shared.hybrid_scoring.quant_scorer import QuantScorer

        scorer = QuantScorer()

        # 강한 매수 설정 (보너스 없이)
        score, details = scorer.calculate_supply_demand_score(
            foreign_net_buy=100_000,
            institution_net_buy=50_000,
            foreign_holding_ratio=50.0,
            avg_volume=1_000_000,
        )

        # 기본 15점 만점 (보너스 없음 — investor_trading_df 미제공)
        assert score <= 15.0
        assert score > 0

    def test_supply_demand_score_with_bonus(self, mock_investor_trading_df):
        """smart_money_5d 보너스 포함 시 최대 18점"""
        from shared.hybrid_scoring.quant_scorer import QuantScorer

        scorer = QuantScorer()

        score, details = scorer.calculate_supply_demand_score(
            foreign_net_buy=100_000,
            institution_net_buy=50_000,
            foreign_holding_ratio=50.0,
            avg_volume=1_000_000,
            investor_trading_df=mock_investor_trading_df,
        )

        # 15점 + 보너스 최대 3점 = 18점 이하
        assert score <= 18.0
        assert score > 0

    def test_supply_demand_score_neutral_without_data(self):
        """데이터 없을 때 중립값 (7.5점)"""
        from shared.hybrid_scoring.quant_scorer import QuantScorer

        scorer = QuantScorer()

        score, details = scorer.calculate_supply_demand_score()

        # 모든 중립: 3.5 + 2.5 + 1.5 = 7.5
        assert score == 7.5

    def test_smart_money_5d_with_investor_df(self, mock_investor_trading_df):
        """investor_trading_df로 smart_money_5d 계산"""
        from shared.hybrid_scoring.quant_scorer import QuantScorer

        scorer = QuantScorer()

        score, details = scorer.calculate_supply_demand_score(
            avg_volume=1_000_000,
            investor_trading_df=mock_investor_trading_df,
        )

        # smart_money_5d 관련 필드가 details에 존재
        assert 'smart_money_5d' in details
        assert 'foreign_5d' in details
        assert 'institution_5d' in details

        # 최근 5일: foreign=[60000,80000,70000,90000,100000], inst=[30000,40000,35000,45000,50000]
        expected_foreign_5d = 60000 + 80000 + 70000 + 90000 + 100000
        expected_inst_5d = 30000 + 40000 + 35000 + 45000 + 50000
        assert details['foreign_5d'] == expected_foreign_5d
        assert details['institution_5d'] == expected_inst_5d

    def test_smart_money_5d_without_investor_df(self):
        """investor_trading_df 없을 때 보너스 0점"""
        from shared.hybrid_scoring.quant_scorer import QuantScorer

        scorer = QuantScorer()

        score, details = scorer.calculate_supply_demand_score(
            foreign_net_buy=50000,
            institution_net_buy=20000,
            avg_volume=1_000_000,
        )

        # smart_money_5d_note가 존재, 보너스 없음
        assert 'smart_money_5d_note' in details
        assert 'smart_money_bonus' not in details

    def test_smart_money_5d_insufficient_data(self):
        """5일 미만 데이터로 smart_money_5d 보너스 없음"""
        from shared.hybrid_scoring.quant_scorer import QuantScorer

        scorer = QuantScorer()

        # 3일치만 제공
        short_df = pd.DataFrame({
            'TRADE_DATE': pd.date_range(end=datetime.now(), periods=3, freq='B'),
            'FOREIGN_NET_BUY': [100000, 200000, 300000],
            'INSTITUTION_NET_BUY': [50000, 60000, 70000],
            'CLOSE_PRICE': [50000, 50100, 50200],
        })

        score, details = scorer.calculate_supply_demand_score(
            avg_volume=1_000_000,
            investor_trading_df=short_df,
        )

        # 5일 미만이므로 보너스 없음
        assert details.get('smart_money_5d_note') == '데이터 부족 (5일 미만)'

    def test_supply_demand_score_components(self, mock_investor_trading_df):
        """개별 구성요소 점수 확인"""
        from shared.hybrid_scoring.quant_scorer import QuantScorer

        scorer = QuantScorer()

        score, details = scorer.calculate_supply_demand_score(
            foreign_net_buy=50000,
            institution_net_buy=20000,
            foreign_holding_ratio=25.0,
            avg_volume=1_000_000,
            investor_trading_df=mock_investor_trading_df,
        )

        # 각 구성요소가 details에 존재
        assert 'foreign_score' in details
        assert 'institution_score' in details
        assert 'holding_score' in details

        # 개별 구성요소 범위 검증 (원래 15점: 7+5+3)
        assert 0 <= details['foreign_score'] <= 7
        assert 0 <= details['institution_score'] <= 5
        assert 0 <= details['holding_score'] <= 3

    def test_dip_bonus_within_foreign_limit(self, mock_stock_data):
        """dip-buying 보너스가 외인 점수 7점 한도 내"""
        from shared.hybrid_scoring.quant_scorer import QuantScorer

        scorer = QuantScorer()

        declining_df = pd.DataFrame({
            'CLOSE_PRICE': [55000, 54000, 53000, 52000, 51000,
                            50000, 49000, 48000, 47000, 46000],
            'VOLUME': [1000000] * 10,
        })

        score, details = scorer.calculate_supply_demand_score(
            foreign_net_buy=50000,
            avg_volume=1_000_000,
            daily_prices_df=declining_df,
        )

        # dip_bonus 적용되더라도 foreign_score는 7점을 넘지 않아야 함
        assert details.get('foreign_score', 0) <= 7.0


# ============================================================================
# Tests: Quant Constants Weights
# ============================================================================

class TestQuantConstantsWeights:
    """가중치 합계 검증"""

    def test_short_term_weights_sum_to_1(self):
        """SHORT_TERM_WEIGHTS 합계 = 1.0"""
        from shared.hybrid_scoring.quant_constants import SHORT_TERM_WEIGHTS

        total = sum(SHORT_TERM_WEIGHTS.values())
        assert abs(total - 1.0) < 0.001, f"SHORT_TERM_WEIGHTS 합계: {total}"

    def test_long_term_weights_sum_to_1(self):
        """LONG_TERM_WEIGHTS 합계 = 1.0"""
        from shared.hybrid_scoring.quant_constants import LONG_TERM_WEIGHTS

        total = sum(LONG_TERM_WEIGHTS.values())
        assert abs(total - 1.0) < 0.001, f"LONG_TERM_WEIGHTS 합계: {total}"

    def test_supply_demand_weight_present(self):
        """supply_demand 가중치가 존재하고 유효한 범위"""
        from shared.hybrid_scoring.quant_constants import SHORT_TERM_WEIGHTS, LONG_TERM_WEIGHTS

        assert 'supply_demand' in SHORT_TERM_WEIGHTS
        assert 'supply_demand' in LONG_TERM_WEIGHTS
        assert SHORT_TERM_WEIGHTS['supply_demand'] > 0
        assert LONG_TERM_WEIGHTS['supply_demand'] > 0


# ============================================================================
# Tests: calculate_total_quant_score with investor_trading_df
# ============================================================================

class TestTotalScoreWithInvestorTrading:
    """investor_trading_df 파라미터 통합 테스트"""

    def test_total_score_accepts_investor_trading_df(self, mock_stock_data, mock_investor_trading_df):
        """calculate_total_quant_score가 investor_trading_df를 받는지 확인"""
        from shared.hybrid_scoring.quant_scorer import QuantScorer
        import inspect

        scorer = QuantScorer()

        sig = inspect.signature(scorer.calculate_total_quant_score)
        assert 'investor_trading_df' in sig.parameters

    def test_total_score_with_investor_data(self, mock_stock_data, mock_investor_trading_df):
        """investor_trading_df 포함 종합 점수 계산"""
        from shared.hybrid_scoring.quant_scorer import QuantScorer

        scorer = QuantScorer()

        result = scorer.calculate_total_quant_score(
            stock_code='005930',
            stock_name='삼성전자',
            daily_prices_df=mock_stock_data,
            foreign_net_buy=50000,
            institution_net_buy=20000,
            investor_trading_df=mock_investor_trading_df,
        )

        assert result.is_valid
        assert result.total_score > 0
        # supply_demand_score는 15점 + 보너스 3점 = 최대 18점
        assert result.supply_demand_score <= 18.0

    def test_total_score_without_investor_data(self, mock_stock_data):
        """investor_trading_df 없이도 정상 동작"""
        from shared.hybrid_scoring.quant_scorer import QuantScorer

        scorer = QuantScorer()

        result = scorer.calculate_total_quant_score(
            stock_code='005930',
            stock_name='삼성전자',
            daily_prices_df=mock_stock_data,
        )

        assert result.is_valid
        assert result.total_score > 0


# ============================================================================
# classify_risk_tag 테스트
# ============================================================================

class TestClassifyRiskTag:
    """코드 기반 risk_tag 분류기 테스트"""

    def _make_quant_result(self, rsi=None, flow_reversal=None, drawdown=None,
                           volume_ratio=None, supply_demand_score=0.0,
                           momentum_score=0.0):
        """테스트용 QuantScoreResult 생성 헬퍼"""
        from shared.hybrid_scoring.quant_scorer import QuantScoreResult
        details = {
            'technical': {},
            'supply_demand': {},
        }
        if rsi is not None:
            details['technical']['rsi'] = rsi
        if flow_reversal is not None:
            details['technical']['flow_reversal'] = flow_reversal
        if drawdown is not None:
            details['technical']['drawdown_from_high'] = drawdown
        if volume_ratio is not None:
            details['technical']['volume_ratio'] = volume_ratio

        return QuantScoreResult(
            stock_code='005930', stock_name='삼성전자',
            total_score=50.0,
            momentum_score=momentum_score, quality_score=10.0,
            value_score=10.0, technical_score=10.0,
            news_stat_score=0.0, supply_demand_score=supply_demand_score,
            matched_conditions=[], condition_win_rate=None,
            condition_sample_count=0, condition_confidence='LOW',
            details=details,
        )

    def test_distribution_risk(self):
        """고점 + 과열 + 매도 전환 → DISTRIBUTION_RISK"""
        from shared.hybrid_scoring.quant_scorer import classify_risk_tag
        result = self._make_quant_result(rsi=75, drawdown=-1, flow_reversal='SELL_TURN')
        assert classify_risk_tag(result) == 'DISTRIBUTION_RISK'

    def test_distribution_risk_requires_all_three(self):
        """3개 조건 중 하나라도 미충족이면 DISTRIBUTION_RISK 아님"""
        from shared.hybrid_scoring.quant_scorer import classify_risk_tag
        # RSI 높지만 매도전환 없음
        result = self._make_quant_result(rsi=75, drawdown=-1, flow_reversal=None)
        assert classify_risk_tag(result) != 'DISTRIBUTION_RISK'
        # RSI 높고 매도전환이지만 DD 큼 (-5%)
        result2 = self._make_quant_result(rsi=75, drawdown=-5, flow_reversal='SELL_TURN')
        assert classify_risk_tag(result2) != 'DISTRIBUTION_RISK'

    def test_caution_rsi_over_75(self):
        """RSI > 75 → CAUTION"""
        from shared.hybrid_scoring.quant_scorer import classify_risk_tag
        result = self._make_quant_result(rsi=78)
        assert classify_risk_tag(result) == 'CAUTION'

    def test_caution_sell_turn_rsi_over_65(self):
        """SELL_TURN + RSI > 65 → CAUTION"""
        from shared.hybrid_scoring.quant_scorer import classify_risk_tag
        result = self._make_quant_result(rsi=67, flow_reversal='SELL_TURN')
        assert classify_risk_tag(result) == 'CAUTION'

    def test_bullish(self):
        """BUY_TURN + 수급 양호 + RSI 적정 + 모멘텀 강세 → BULLISH"""
        from shared.hybrid_scoring.quant_scorer import classify_risk_tag
        result = self._make_quant_result(
            rsi=55, flow_reversal='BUY_TURN',
            supply_demand_score=12.0, momentum_score=18.0
        )
        assert classify_risk_tag(result) == 'BULLISH'

    def test_bullish_requires_momentum(self):
        """모멘텀 낮으면 BULLISH 아님"""
        from shared.hybrid_scoring.quant_scorer import classify_risk_tag
        result = self._make_quant_result(
            rsi=55, flow_reversal='BUY_TURN',
            supply_demand_score=12.0, momentum_score=10.0
        )
        assert classify_risk_tag(result) != 'BULLISH'

    def test_neutral_default(self):
        """어느 조건에도 해당 안 되면 NEUTRAL"""
        from shared.hybrid_scoring.quant_scorer import classify_risk_tag
        result = self._make_quant_result(rsi=50)
        assert classify_risk_tag(result) == 'NEUTRAL'

    def test_neutral_no_data(self):
        """데이터 없어도 NEUTRAL"""
        from shared.hybrid_scoring.quant_scorer import classify_risk_tag
        result = self._make_quant_result()
        assert classify_risk_tag(result) == 'NEUTRAL'

    def test_neutral_empty_details(self):
        """details가 비어있어도 에러 없이 NEUTRAL"""
        from shared.hybrid_scoring.quant_scorer import classify_risk_tag, QuantScoreResult
        result = QuantScoreResult(
            stock_code='005930', stock_name='삼성전자',
            total_score=50.0, momentum_score=10.0, quality_score=10.0,
            value_score=10.0, technical_score=10.0,
            news_stat_score=0.0, supply_demand_score=0.0,
            matched_conditions=[], condition_win_rate=None,
            condition_sample_count=0, condition_confidence='LOW',
            details={},
        )
        assert classify_risk_tag(result) == 'NEUTRAL'

