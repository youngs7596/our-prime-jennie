"""
tests/services/scout-job/test_scout_pipeline.py - Scout Pipeline 통합 테스트
=============================================================================

process_unified_analyst_task() 통합 Analyst 파이프라인 테스트
"""

import pytest
from unittest.mock import MagicMock, patch
import sys
import os

# scout_pipeline.py가 services/scout-job/ 안에 있으므로 경로 추가
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', 'services', 'scout-job'))


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def mock_quant_result():
    """Mock QuantScoreResult"""
    from shared.hybrid_scoring.quant_scorer import QuantScoreResult
    return QuantScoreResult(
        stock_code='005930',
        stock_name='삼성전자',
        total_score=72.0,
        momentum_score=18.0,
        quality_score=15.0,
        value_score=12.0,
        technical_score=8.0,
        news_stat_score=10.0,
        supply_demand_score=9.0,
        matched_conditions=['RSI_OVERSOLD'],
        condition_win_rate=55.0,
        condition_sample_count=30,
        condition_confidence='MEDIUM',
        details={
            'technical': {'rsi': 55, 'volume_ratio': 1.2, 'ma20_slope_5d': 0.5},
            'supply_demand': {'foreign_ratio': 2.5},
        },
    )


@pytest.fixture
def mock_brain():
    """Mock JennieBrain"""
    brain = MagicMock()
    brain.run_analyst_scoring.return_value = {
        'score': 74,
        'grade': 'A',
        'reason': '정량 72점 기반, 반도체 수주 확인으로 +2점 보정',
    }
    return brain


@pytest.fixture
def mock_snapshot_cache():
    return {
        '005930': {
            'per': 12.5, 'pbr': 1.1, 'roe': 15.0,
            'market_cap': 400000000, 'sales_growth': 5.0, 'eps_growth': 3.0,
        },
    }


@pytest.fixture
def mock_news_cache():
    return {
        '005930': '삼성전자 AI 반도체 수주 확대 기대',
    }


# ============================================================================
# process_unified_analyst_task 테스트
# ============================================================================

class TestProcessUnifiedAnalystTask:
    """통합 Analyst 파이프라인 테스트"""

    @patch('scout_pipeline.database')
    def test_basic_flow(self, mock_db, mock_brain, mock_quant_result,
                        mock_snapshot_cache, mock_news_cache):
        """기본 실행 흐름: 정상 종목 분석"""
        from scout_pipeline import process_unified_analyst_task

        mock_db.get_competitor_benefit_score.return_value = {'score': 0, 'reason': ''}

        stock_info = {'code': '005930', 'info': {'name': '삼성전자', 'reasons': ['KOSPI 시총 상위']}}
        result = process_unified_analyst_task(
            stock_info, mock_brain, mock_quant_result,
            mock_snapshot_cache, mock_news_cache
        )

        assert result['code'] == '005930'
        assert result['name'] == '삼성전자'
        assert 'llm_score' in result
        assert 'trade_tier' in result
        assert result['llm_metadata']['source'] == 'unified_analyst'

    @patch('scout_pipeline.database')
    def test_guardrail_clamps_score(self, mock_db, mock_brain, mock_quant_result,
                                     mock_snapshot_cache, mock_news_cache):
        """±15pt 가드레일: LLM 점수가 정량 ±15pt 범위로 클램핑"""
        from scout_pipeline import process_unified_analyst_task

        mock_db.get_competitor_benefit_score.return_value = {'score': 0, 'reason': ''}
        # LLM이 95점을 줘도 quant(72) + 15 = 87로 클램핑
        mock_brain.run_analyst_scoring.return_value = {
            'score': 95, 'grade': 'S', 'reason': 'LLM 과잉 낙관'
        }

        stock_info = {'code': '005930', 'info': {'name': '삼성전자', 'reasons': []}}
        result = process_unified_analyst_task(
            stock_info, mock_brain, mock_quant_result,
            mock_snapshot_cache, mock_news_cache
        )

        # LLM clamped score = min(72+15, 95) = 87
        assert result['llm_metadata']['llm_clamped_score'] == 87
        assert result['llm_metadata']['llm_raw_score'] == 95

    @patch('scout_pipeline.database')
    def test_guardrail_clamps_low_score(self, mock_db, mock_brain, mock_quant_result,
                                         mock_snapshot_cache, mock_news_cache):
        """±15pt 가드레일: LLM이 낮은 점수를 줘도 quant - 15 이하로 내려가지 않음"""
        from scout_pipeline import process_unified_analyst_task

        mock_db.get_competitor_benefit_score.return_value = {'score': 0, 'reason': ''}
        # LLM이 30점을 줘도 quant(72) - 15 = 57로 클램핑
        mock_brain.run_analyst_scoring.return_value = {
            'score': 30, 'grade': 'D', 'reason': 'LLM 과잉 비관'
        }

        stock_info = {'code': '005930', 'info': {'name': '삼성전자', 'reasons': []}}
        result = process_unified_analyst_task(
            stock_info, mock_brain, mock_quant_result,
            mock_snapshot_cache, mock_news_cache
        )

        assert result['llm_metadata']['llm_clamped_score'] == 57
        assert result['llm_metadata']['llm_raw_score'] == 30

    @patch('scout_pipeline.database')
    def test_code_based_risk_tag(self, mock_db, mock_brain, mock_quant_result,
                                  mock_snapshot_cache, mock_news_cache):
        """risk_tag는 코드 기반으로 결정 (LLM이 아닌 classify_risk_tag)"""
        from scout_pipeline import process_unified_analyst_task

        mock_db.get_competitor_benefit_score.return_value = {'score': 0, 'reason': ''}

        stock_info = {'code': '005930', 'info': {'name': '삼성전자', 'reasons': []}}
        result = process_unified_analyst_task(
            stock_info, mock_brain, mock_quant_result,
            mock_snapshot_cache, mock_news_cache
        )

        # RSI=55, no flow_reversal → NEUTRAL
        assert result['llm_metadata']['risk_tag'] == 'NEUTRAL'

    @patch('scout_pipeline.database')
    def test_no_snapshot_returns_error(self, mock_db, mock_brain, mock_quant_result,
                                       mock_news_cache):
        """스냅샷 없으면 에러 결과 반환"""
        from scout_pipeline import process_unified_analyst_task

        stock_info = {'code': '005930', 'info': {'name': '삼성전자', 'reasons': []}}
        result = process_unified_analyst_task(
            stock_info, mock_brain, mock_quant_result,
            snapshot_cache={}, news_cache=mock_news_cache
        )

        assert result['is_tradable'] is False
        assert result['trade_tier'] == 'BLOCKED'

    @patch('scout_pipeline.database')
    def test_competitor_bonus_applied(self, mock_db, mock_brain, mock_quant_result,
                                      mock_snapshot_cache, mock_news_cache):
        """경쟁사 수혜 가산점 적용"""
        from scout_pipeline import process_unified_analyst_task

        mock_db.get_competitor_benefit_score.return_value = {'score': 5, 'reason': 'SK하이닉스 화재'}

        stock_info = {'code': '005930', 'info': {'name': '삼성전자', 'reasons': []}}
        result = process_unified_analyst_task(
            stock_info, mock_brain, mock_quant_result,
            mock_snapshot_cache, mock_news_cache
        )

        # LLM raw=74, clamped to max(72+15,74)=74, then +5 bonus = 79
        assert result['llm_metadata']['llm_clamped_score'] == 79

    @patch('scout_pipeline.database')
    def test_veto_on_distribution_risk(self, mock_db, mock_brain,
                                        mock_snapshot_cache, mock_news_cache):
        """DISTRIBUTION_RISK → Veto 발동 (is_tradable=False, BLOCKED)"""
        from scout_pipeline import process_unified_analyst_task
        from shared.hybrid_scoring.quant_scorer import QuantScoreResult

        mock_db.get_competitor_benefit_score.return_value = {'score': 0, 'reason': ''}

        # DISTRIBUTION_RISK 조건: RSI>70 + DD>-3 + SELL_TURN
        quant_result = QuantScoreResult(
            stock_code='005930', stock_name='삼성전자',
            total_score=75.0, momentum_score=18.0, quality_score=15.0,
            value_score=12.0, technical_score=8.0,
            news_stat_score=10.0, supply_demand_score=12.0,
            matched_conditions=[], condition_win_rate=55.0,
            condition_sample_count=30, condition_confidence='MEDIUM',
            details={
                'technical': {
                    'rsi': 75, 'drawdown_from_high': -1,
                    'flow_reversal': 'SELL_TURN',
                },
                'supply_demand': {},
            },
        )

        stock_info = {'code': '005930', 'info': {'name': '삼성전자', 'reasons': []}}
        result = process_unified_analyst_task(
            stock_info, mock_brain, quant_result,
            mock_snapshot_cache, mock_news_cache
        )

        assert result['llm_metadata']['risk_tag'] == 'DISTRIBUTION_RISK'
        assert result['llm_metadata']['veto_applied'] is True
        assert result['is_tradable'] is False
        assert result['trade_tier'] == 'BLOCKED'

    @patch('scout_pipeline.database')
    def test_trade_tier_tier1(self, mock_db, mock_brain,
                               mock_snapshot_cache, mock_news_cache):
        """hybrid >= 75 → TIER1"""
        from scout_pipeline import process_unified_analyst_task
        from shared.hybrid_scoring.quant_scorer import QuantScoreResult

        mock_db.get_competitor_benefit_score.return_value = {'score': 0, 'reason': ''}
        mock_brain.run_analyst_scoring.return_value = {
            'score': 82, 'grade': 'S', 'reason': '강력 호재'
        }

        quant_result = QuantScoreResult(
            stock_code='005930', stock_name='삼성전자',
            total_score=80.0, momentum_score=20.0, quality_score=15.0,
            value_score=12.0, technical_score=10.0,
            news_stat_score=12.0, supply_demand_score=11.0,
            matched_conditions=[], condition_win_rate=60.0,
            condition_sample_count=50, condition_confidence='HIGH',
            details={'technical': {'rsi': 55}, 'supply_demand': {}},
        )

        stock_info = {'code': '005930', 'info': {'name': '삼성전자', 'reasons': []}}
        result = process_unified_analyst_task(
            stock_info, mock_brain, quant_result,
            mock_snapshot_cache, mock_news_cache
        )

        assert result['trade_tier'] == 'TIER1'
        assert result['is_tradable'] is True
