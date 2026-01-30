"""
tests/shared/test_market_regime.py - 시장 국면 분석 테스트
=========================================================

shared/market_regime.py의 MarketRegimeDetector 및 StrategySelector를 테스트합니다.
"""

import pytest
import pandas as pd
import numpy as np
from unittest.mock import MagicMock, patch



# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def detector():
    """MarketRegimeDetector 인스턴스"""
    from shared.market_regime import MarketRegimeDetector
    return MarketRegimeDetector()


@pytest.fixture
def selector():
    """StrategySelector 인스턴스"""
    from shared.market_regime import StrategySelector
    return StrategySelector()


@pytest.fixture
def sample_kospi_df():
    """샘플 KOSPI 데이터프레임 (30일 - MA20 계산 충분)"""
    # 기본 상승 추세
    base_price = 2500
    prices = [base_price + i * 5 for i in range(30)]  # 2500 → 2645
    
    return pd.DataFrame({
        'CLOSE_PRICE': prices
    })


@pytest.fixture
def bull_kospi_df():
    """상승장 KOSPI 데이터 (30일)"""
    # MA20 대비 크게 위에 있는 상승 추세
    base_price = 2500
    prices = [base_price + i * 10 for i in range(30)]  # 2500 → 2790 (급등)
    
    return pd.DataFrame({
        'CLOSE_PRICE': prices
    })


@pytest.fixture
def bear_kospi_df():
    """하락장 KOSPI 데이터 (30일)"""
    # MA20 대비 아래에 있는 하락 추세
    base_price = 2700
    prices = [base_price - i * 10 for i in range(30)]  # 2700 → 2410 (하락)
    
    return pd.DataFrame({
        'CLOSE_PRICE': prices
    })


@pytest.fixture
def sideways_kospi_df():
    """횡보장 KOSPI 데이터 (30일)"""
    # MA20 근처에서 횡보
    base_price = 2500
    prices = [base_price + (i % 3 - 1) * 5 for i in range(30)]  # 작은 변동
    
    return pd.DataFrame({
        'CLOSE_PRICE': prices
    })


# ============================================================================
# Tests: MarketRegimeDetector
# ============================================================================

class TestMarketRegimeDetector:
    """MarketRegimeDetector 테스트"""
    
    def test_detect_regime_bull(self, detector, bull_kospi_df):
        """상승장 감지"""
        current_price = 2750  # MA20 대비 위
        
        regime, context = detector.detect_regime(bull_kospi_df, current_price, quiet=True)
        
        assert regime in ['BULL', 'STRONG_BULL']
        assert 'kospi_current' in context
        assert context['kospi_current'] == current_price
    
    def test_detect_regime_bear(self, detector, bear_kospi_df):
        """하락장 감지"""
        current_price = 2400  # MA20 대비 아래
        
        regime, context = detector.detect_regime(bear_kospi_df, current_price, quiet=True)
        
        assert regime == 'BEAR'
        assert 'return_5d_pct' in context
    
    def test_detect_regime_sideways(self, detector, sideways_kospi_df):
        """횡보장 감지"""
        current_price = 2500  # MA 근처
        
        regime, context = detector.detect_regime(sideways_kospi_df, current_price, quiet=True)
        
        assert regime in ['SIDEWAYS', 'BULL']  # 횡보 또는 약한 상승
    
    def test_detect_regime_insufficient_data(self, detector):
        """데이터 부족 시 기본값"""
        small_df = pd.DataFrame({'CLOSE_PRICE': [2500, 2510, 2505]})  # 3일만
        
        regime, context = detector.detect_regime(small_df, 2510, quiet=True)
        
        assert regime == 'SIDEWAYS'  # 기본값
        assert 'error' in context
    
    def test_detect_regime_empty_df(self, detector):
        """빈 데이터프레임"""
        empty_df = pd.DataFrame({'CLOSE_PRICE': []})
        
        regime, context = detector.detect_regime(empty_df, 2500, quiet=True)
        
        assert regime == 'SIDEWAYS'
        assert 'error' in context
    
    def test_detect_regime_uses_ma10_for_short_data(self, detector):
        """10~19일 데이터는 MA10 사용"""
        # 12일 데이터
        prices = [2500 + i * 5 for i in range(12)]
        short_df = pd.DataFrame({'CLOSE_PRICE': prices})
        
        regime, context = detector.detect_regime(short_df, 2560, quiet=True)
        
        assert context.get('using_ma10', False) is True
    
    def test_detect_regime_strong_bull(self, detector):
        """급등장 감지"""
        # 급등 데이터: 5일간 5% 이상 상승 (30일 데이터)
        base = 2500
        prices = [base] * 25 + [base * 1.01, base * 1.02, base * 1.03, base * 1.04, base * 1.05]
        df = pd.DataFrame({'CLOSE_PRICE': prices})
        
        current_price = base * 1.06  # MA 대비 높음
        
        regime, context = detector.detect_regime(df, current_price, quiet=True)
        
        # 급등장 또는 상승장
        assert regime in ['STRONG_BULL', 'BULL']
    
    def test_detect_regime_returns_scores(self, detector, sample_kospi_df):
        """국면별 점수 반환"""
        regime, context = detector.detect_regime(sample_kospi_df, 2600, quiet=True)
        
        assert 'regime_scores' in context
        assert 'BULL' in context['regime_scores']
        assert 'BEAR' in context['regime_scores']
        assert 'SIDEWAYS' in context['regime_scores']
        assert 'STRONG_BULL' in context['regime_scores']


# ============================================================================
# Tests: get_dynamic_risk_setting
# ============================================================================

class TestDynamicRiskSetting:
    """동적 리스크 설정 테스트"""
    
    def test_strong_bull_settings(self, detector):
        """급등장 리스크 설정"""
        settings = detector.get_dynamic_risk_setting('STRONG_BULL')

        assert settings['stop_loss_pct'] == -0.07  # Updated 2026-01-30: 급등장만 -7%
        assert settings['target_profit_pct'] == 0.15  # 길게 먹기
        assert settings['position_size_ratio'] == 1.0  # 풀시드

    def test_bull_settings(self, detector):
        """상승장 리스크 설정"""
        settings = detector.get_dynamic_risk_setting('BULL')

        assert settings['stop_loss_pct'] == -0.05
        assert settings['target_profit_pct'] == 0.10
        assert settings['position_size_ratio'] == 1.0

    def test_sideways_settings(self, detector):
        """횡보장 리스크 설정"""
        settings = detector.get_dynamic_risk_setting('SIDEWAYS')

        assert settings['stop_loss_pct'] == -0.05
        assert settings['target_profit_pct'] == 0.10
        assert settings['position_size_ratio'] == 0.5  # 비중 축소
    
    def test_bear_settings(self, detector):
        """하락장 리스크 설정"""
        settings = detector.get_dynamic_risk_setting('BEAR')
        
        assert settings['stop_loss_pct'] == -0.02  # 칼손절
        assert settings['target_profit_pct'] == 0.03  # 반등만 먹기
        assert settings['position_size_ratio'] == 0.3  # 정찰병 수준
    
    def test_unknown_regime_default(self, detector):
        """알 수 없는 국면은 기본값"""
        settings = detector.get_dynamic_risk_setting('UNKNOWN')
        
        assert settings['stop_loss_pct'] == -0.03
        assert settings['target_profit_pct'] == 0.05
        assert settings['position_size_ratio'] == 0.5


# ============================================================================
# Tests: StrategySelector
# ============================================================================

class TestStrategySelector:
    """StrategySelector 테스트"""
    
    def test_select_strategies_strong_bull(self, selector):
        """급등장 전략 선택"""
        strategies = selector.select_strategies('STRONG_BULL')
        
        assert 'VOLUME_MOMENTUM' in strategies
        assert 'RESISTANCE_BREAKOUT' in strategies
        assert 'TREND_FOLLOWING' in strategies
    
    def test_select_strategies_bull(self, selector):
        """상승장 전략 선택"""
        strategies = selector.select_strategies('BULL')
        
        assert 'VOLUME_MOMENTUM' in strategies
        assert 'TREND_FOLLOWING' in strategies
        assert 'MEAN_REVERSION' in strategies
    
    def test_select_strategies_sideways(self, selector):
        """횡보장 전략 선택"""
        strategies = selector.select_strategies('SIDEWAYS')
        
        assert 'MEAN_REVERSION' in strategies
        assert 'TREND_FOLLOWING' in strategies
    
    def test_select_strategies_bear(self, selector):
        """하락장 전략 선택 (Project Recon: 제한적 추세 추종)"""
        strategies = selector.select_strategies('BEAR')
        
        # [Project Recon] ENABLE_RECON_IN_BEAR=True(기본값)일 때 제한적 추세 추종 허용
        # 기본값이 True이므로 TREND_FOLLOWING이 포함됨
        assert strategies == ['TREND_FOLLOWING'] or strategies == []
    
    def test_select_strategies_unknown_default(self, selector):
        """알 수 없는 국면은 기본 전략"""
        strategies = selector.select_strategies('UNKNOWN')
        
        assert 'MEAN_REVERSION' in strategies


# ============================================================================
# Tests: map_llm_strategy
# ============================================================================

class TestMapLlmStrategy:
    """LLM 전략 매핑 테스트"""
    
    def test_map_snipe_dip(self, selector):
        """SNIPE_DIP 매핑"""
        result = selector.map_llm_strategy('SNIPE_DIP')
        
        assert result == 'BEAR_SNIPE_DIP'
    
    def test_map_momentum_breakout(self, selector):
        """MOMENTUM_BREAKOUT 매핑"""
        result = selector.map_llm_strategy('MOMENTUM_BREAKOUT')
        
        assert result == 'BEAR_MOMENTUM_BREAKOUT'
    
    def test_map_unknown_strategy(self, selector):
        """알 수 없는 전략은 None"""
        result = selector.map_llm_strategy('UNKNOWN_STRATEGY')
        
        assert result is None


# ============================================================================
# Tests: Edge Cases
# ============================================================================

class TestEdgeCases:
    """Edge Cases 테스트"""
    
    def test_extreme_price_movement(self, detector):
        """극단적인 가격 변동 (30일 데이터)"""
        # 폭락 후 급등
        prices = [3000] * 25 + [2500, 2400, 2300, 2200, 3000]  # 마지막에 급등
        df = pd.DataFrame({'CLOSE_PRICE': prices})
        
        regime, context = detector.detect_regime(df, 3000, quiet=True)
        
        # 어떤 값이든 에러 없이 반환
        assert regime in ['STRONG_BULL', 'BULL', 'SIDEWAYS', 'BEAR']
    
    def test_constant_prices(self, detector):
        """가격 변화 없음 (30일 데이터)"""
        prices = [2500] * 30
        df = pd.DataFrame({'CLOSE_PRICE': prices})
        
        regime, context = detector.detect_regime(df, 2500, quiet=True)
        
        assert regime == 'SIDEWAYS'
    
    def test_regime_cache(self, detector):
        """캐시 존재 확인"""
        assert hasattr(detector, 'regime_cache')
        assert isinstance(detector.regime_cache, dict)
    
    def test_strategy_constants(self, selector):
        """전략 상수 정의 확인"""
        assert selector.STRATEGY_MEAN_REVERSION == "MEAN_REVERSION"
        assert selector.STRATEGY_TREND_FOLLOWING == "TREND_FOLLOWING"
        assert selector.STRATEGY_VOLUME_MOMENTUM == "VOLUME_MOMENTUM"
        assert selector.STRATEGY_BEAR_SNIPE_DIP == "BEAR_SNIPE_DIP"


# ============================================================================
# Tests: Macro Insight Integration (3현자 Council 권고)
# ============================================================================

class TestMacroInsightIntegration:
    """매크로 인사이트 연동 테스트"""

    def test_detect_regime_with_macro_no_macro_data(self, detector, sample_kospi_df):
        """매크로 데이터 없을 때 기본 동작"""
        # 매크로 캐시가 비어있으면 기본 가격 기반 분석만 수행
        regime, context = detector.detect_regime_with_macro(
            sample_kospi_df, 2600, quiet=True
        )

        assert regime in ['STRONG_BULL', 'BULL', 'SIDEWAYS', 'BEAR']
        # 매크로 정보가 context에 포함됨
        assert 'macro_signal' in context or 'error' not in context

    @patch('shared.macro_insight.get_macro_regime_adjustment')
    @patch('shared.macro_insight.apply_macro_adjustment_to_regime')
    def test_detect_regime_with_macro_bullish(
        self, mock_apply, mock_get, detector, sample_kospi_df
    ):
        """매크로 RISK_ON 신호 반영"""
        # Mock 설정
        mock_get.return_value = {
            "should_adjust": True,
            "adjustment_weight": 0.08,
            "suggested_direction": "bullish",
            "signal_details": {"signal_type": "RISK_ON"},
        }
        mock_apply.return_value = (
            "BULL",
            {
                "regime_scores": {"BULL": 90},
                "macro_signal": {"signal_type": "RISK_ON"},
                "macro_influence": {
                    "should_adjust": True,
                    "weight": 0.08,
                    "direction": "bullish",
                },
            }
        )

        regime, context = detector.detect_regime_with_macro(
            sample_kospi_df, 2600, quiet=True
        )

        assert regime == "BULL"
        assert context["macro_influence"]["direction"] == "bullish"

    @patch('shared.macro_insight.get_macro_regime_adjustment')
    @patch('shared.macro_insight.apply_macro_adjustment_to_regime')
    def test_detect_regime_with_macro_risk_off_hint(
        self, mock_apply, mock_get, detector, sample_kospi_df
    ):
        """매크로 RISK_OFF_HINT는 단독 발동 금지 (3현자 핵심 권고)"""
        # Mock 설정
        mock_get.return_value = {
            "should_adjust": False,  # 단독 발동 금지
            "adjustment_weight": 0.0,
            "suggested_direction": "bearish_hint",
            "signal_details": {"signal_type": "RISK_OFF_HINT"},
            "reason": "risk_off_hint_cannot_trigger_alone",
        }
        mock_apply.return_value = (
            "SIDEWAYS",  # Regime 변경 없음
            {
                "regime_scores": {"SIDEWAYS": 70},
                "macro_signal": {"signal_type": "RISK_OFF_HINT"},
                "macro_influence": {
                    "should_adjust": False,
                    "direction": "bearish_hint",
                    "warning": "매크로 부정 신호 감지. 주의 필요.",
                },
            }
        )

        regime, context = detector.detect_regime_with_macro(
            sample_kospi_df, 2500, quiet=True
        )

        # RISK_OFF_HINT는 Regime을 변경하지 않음
        assert regime == "SIDEWAYS"
        assert context["macro_influence"]["should_adjust"] is False
        assert "warning" in context["macro_influence"]

    def test_detect_regime_with_macro_import_error(self, detector, sample_kospi_df):
        """macro_insight 모듈 없을 때 fallback"""
        with patch.dict('sys.modules', {'shared.macro_insight': None}):
            # ImportError가 발생해도 기본 분석 결과 반환
            regime, context = detector.detect_regime_with_macro(
                sample_kospi_df, 2600, quiet=True
            )

            assert regime in ['STRONG_BULL', 'BULL', 'SIDEWAYS', 'BEAR']

    def test_detect_regime_with_macro_max_weight(self, detector, sample_kospi_df):
        """외부 정보 가중치 ≤10% 확인 (3현자 권고)"""
        from shared.macro_insight.macro_sentiment_analyzer import MAX_EXTERNAL_WEIGHT

        assert MAX_EXTERNAL_WEIGHT <= 0.10

