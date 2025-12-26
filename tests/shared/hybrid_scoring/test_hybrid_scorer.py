"""
tests/shared/hybrid_scoring/test_hybrid_scorer.py - HybridScorer 테스트
=====================================================================

shared/hybrid_scoring/hybrid_scorer.py의 하이브리드 스코어링을 테스트합니다.
"""

import sys
from unittest.mock import MagicMock, patch

# [CRITICAL] Mocking external heavy dependencies to avoid import errors during test collection
sys.modules["numpy"] = MagicMock()
sys.modules["pandas"] = MagicMock()
sys.modules["pytz"] = MagicMock()
sys.modules["dateutil"] = MagicMock()

import pytest
from dataclasses import asdict


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
        momentum_score=15.0,
        quality_score=20.0,
        value_score=12.0,
        technical_score=15.0,
        news_stat_score=5.0,
        supply_demand_score=5.0,
        matched_conditions=['rsi_oversold', 'foreign_buy'],
        condition_win_rate=0.65,
        condition_sample_count=45,
        condition_confidence='MID',
        news_stat_sample_count=50,
        short_term_score=70.0,
        short_term_grade='A',
        short_term_recommendation='BUY',
        long_term_score=60.0,
        long_term_grade='B',
        long_term_recommendation='HOLD',
        recommended_holding_days=5,
        invalid_reason=None,
        news_timing_signal="WAIT_FOR_DIP",
        news_timing_reason="News spike",
        compound_bonus=5.0
    )


@pytest.fixture
def scorer():
    """HybridScorer 인스턴스"""
    from shared.hybrid_scoring.hybrid_scorer import HybridScorer
    return HybridScorer(market_regime='BULL')


# ============================================================================
# Tests: HybridScoreResult 데이터클래스
# ============================================================================

class TestHybridScoreResult:
    """HybridScoreResult 데이터클래스 테스트"""
    
    def test_create_result(self):
        """결과 생성"""
        from shared.hybrid_scoring.hybrid_scorer import HybridScoreResult
        
        result = HybridScoreResult(
            stock_code='005930',
            stock_name='삼성전자',
            quant_score=72.0,
            llm_score=75.0,
            hybrid_score=73.2,
            quant_weight=0.6,
            llm_weight=0.4
        )
        
        assert result.stock_code == '005930'
        assert result.hybrid_score == 73.2
    
    def test_to_watchlist_entry(self):
        """Watchlist 변환"""
        from shared.hybrid_scoring.hybrid_scorer import HybridScoreResult
        
        result = HybridScoreResult(
            stock_code='005930',
            stock_name='삼성전자',
            quant_score=72.0,
            llm_score=75.0,
            hybrid_score=73.2,
            quant_weight=0.6,
            llm_weight=0.4,
            grade='B',
            llm_reason='좋은 종목입니다.'
        )
        
        entry = result.to_watchlist_entry()
        
        assert entry['code'] == '005930'
        assert entry['name'] == '삼성전자'


# ============================================================================
# Tests: HybridScorer 초기화
# ============================================================================

class TestHybridScorerInit:
    """HybridScorer 초기화 테스트"""
    
    def test_init_bull_market(self):
        """상승장 초기화"""
        from shared.hybrid_scoring.hybrid_scorer import HybridScorer
        
        scorer = HybridScorer(market_regime='BULL')
        
        assert scorer is not None
    
    def test_init_bear_market(self):
        """하락장 초기화"""
        from shared.hybrid_scoring.hybrid_scorer import HybridScorer
        
        scorer = HybridScorer(market_regime='BEAR')
        
        assert scorer is not None
    
    def test_init_default_regime(self):
        """기본 국면"""
        from shared.hybrid_scoring.hybrid_scorer import HybridScorer
        
        scorer = HybridScorer()
        
        assert scorer is not None


# ============================================================================
# Tests: calculate_hybrid_score
# ============================================================================

class TestCalculateHybridScore:
    """하이브리드 점수 계산 테스트"""
    
    def test_basic_calculation(self, scorer, mock_quant_result):
        """기본 계산"""
        result = scorer.calculate_hybrid_score(
            quant_result=mock_quant_result,
            llm_score=75.0,
            llm_reason='좋은 종목입니다.'
        )
        
        assert result is not None
        assert result.quant_score == 72.0
        assert result.llm_score == 75.0
        # hybrid_score = quant_score * quant_weight + llm_score * llm_weight
        assert 70 <= result.hybrid_score <= 80
    
    def test_default_weights(self, scorer, mock_quant_result):
        """기본 가중치 (60:40)"""
        result = scorer.calculate_hybrid_score(
            quant_result=mock_quant_result,
            llm_score=75.0
        )
        
        # 기본: 정량 60%, LLM 40%
        expected = 72.0 * 0.6 + 75.0 * 0.4
        
        # 안전장치가 적용되지 않으면 가까운 값
        assert abs(result.hybrid_score - expected) < 10
    
    def test_grade_assignment(self, scorer, mock_quant_result):
        """등급 할당"""
        result = scorer.calculate_hybrid_score(
            quant_result=mock_quant_result,
            llm_score=75.0
        )
        
        # 70~79점 → B 등급
        assert result.grade in ['A', 'B', 'C', 'D']
    
    def test_safety_lock_large_gap(self, scorer, mock_quant_result):
        """점수 차이 30점 이상 → 안전장치 발동"""
        # 정량 72점, LLM 100점 → 차이 28점 (경계값)
        result = scorer.calculate_hybrid_score(
            quant_result=mock_quant_result,
            llm_score=100.0  # 차이 28점
        )
        
        # 안전장치가 발동하면 낮은 쪽으로 가중치 이동
        # hybrid_score는 단순 가중 평균보다 낮을 수 있음
        assert result.hybrid_score < (72.0 * 0.5 + 100.0 * 0.5)
    
    def test_condition_info_preserved(self, scorer, mock_quant_result):
        """조건부 승률 정보 보존"""
        result = scorer.calculate_hybrid_score(
            quant_result=mock_quant_result,
            llm_score=75.0
        )
        
        assert result.condition_win_rate == 0.65
        assert result.condition_sample_count == 45


# ============================================================================
# Tests: 최소 품질 기준
# ============================================================================

class TestMinimumQualityThreshold:
    """최소 품질 기준 테스트"""
    
    def test_below_minimum_threshold(self, scorer):
        """40점 미만 → 자동 탈락"""
        from shared.hybrid_scoring.quant_scorer import QuantScoreResult
        
        low_quant = QuantScoreResult(
            stock_code='999999',
            stock_name='저품질종목',
            total_score=30.0,  # 40점 미만
            momentum_score=5.0,
            quality_score=5.0,
            value_score=5.0,
            technical_score=5.0,
            news_stat_score=5.0,
            supply_demand_score=5.0,
            matched_conditions=[],
            condition_win_rate=None,
            condition_sample_count=0,
            condition_confidence='LOW'
        )
        
        result = scorer.calculate_hybrid_score(
            quant_result=low_quant,
            llm_score=80.0  # LLM 높아도
        )
        
        # 최소 기준 미달 시 안전장치 발동
        assert result.safety_lock_applied or result.hybrid_score < 50


# ============================================================================
# Tests: 시장 국면별 가중치
# ============================================================================

class TestMarketRegimeWeights:
    """시장 국면별 가중치 테스트"""
    
    def test_bull_market_weights(self, mock_quant_result):
        """상승장 가중치"""
        from shared.hybrid_scoring.hybrid_scorer import HybridScorer
        
        scorer = HybridScorer(market_regime='BULL')
        result = scorer.calculate_hybrid_score(mock_quant_result, 75.0)
        
        # 상승장: 기본 가중치
        assert result.quant_weight >= 0.5
    
    def test_bear_market_weights(self, mock_quant_result):
        """하락장 가중치"""
        from shared.hybrid_scoring.hybrid_scorer import HybridScorer
        
        scorer = HybridScorer(market_regime='BEAR')
        result = scorer.calculate_hybrid_score(mock_quant_result, 75.0)
        
        # 하락장: 정량 가중치 상향 가능
        assert result.quant_weight >= 0.5


# ============================================================================
# Tests: format_quant_score_for_prompt
# ============================================================================

class TestFormatQuantScoreForPrompt:
    """정량 점수 프롬프트 포맷 테스트"""
    
    def test_format_basic(self, mock_quant_result):
        """기본 포맷"""
        from shared.hybrid_scoring.quant_scorer import format_quant_score_for_prompt
        
        prompt = format_quant_score_for_prompt(mock_quant_result)
        
        assert isinstance(prompt, str)
        assert '삼성전자' in prompt
        assert '72' in prompt  # total_score
    
    def test_format_includes_factors(self, mock_quant_result):
        """팩터 점수 포함"""
        from shared.hybrid_scoring.quant_scorer import format_quant_score_for_prompt
        
        prompt = format_quant_score_for_prompt(mock_quant_result)
        
        # 주요 팩터 포함
        assert '모멘텀' in prompt or 'momentum' in prompt.lower()
        assert '품질' in prompt or 'quality' in prompt.lower()
    
    def test_format_includes_win_rate(self, mock_quant_result):
        """승률 정보 포함"""
        from shared.hybrid_scoring.quant_scorer import format_quant_score_for_prompt
        
        prompt = format_quant_score_for_prompt(mock_quant_result)
        
        assert '65' in prompt or '0.65' in prompt  # win_rate
        assert '45' in prompt  # sample_count


# ============================================================================
# Tests: run_hybrid_scoring_pipeline
# ============================================================================


# ============================================================================
# Tests: Batch Processing
# ============================================================================

class TestBatchProcessing:
    """배치 처리 테스트"""

    def test_batch_calculation_empty(self, scorer):
        """빈 입력"""
        results = scorer.calculate_batch_hybrid_scores(
            quant_results=[],
            llm_scores={}
        )
        assert results == []

    def test_batch_calculation_success(self, scorer, mock_quant_result):
        """정상 배치 계산"""
        llm_scores = {
            '005930': (80.0, "Great stock")
        }
        
        results = scorer.calculate_batch_hybrid_scores(
            quant_results=[mock_quant_result],
            llm_scores=llm_scores
        )
        
        assert len(results) == 1
        assert results[0].stock_code == '005930'
        assert results[0].llm_score == 80.0
        assert results[0].llm_reason == "Great stock"

    def test_batch_calculation_partial_llm(self, scorer, mock_quant_result):
        """일부 종목만 LLM 점수 있음 (없는 종목은 기본값 사용)"""
        # mock_quant_result code is '005930'
        
        # LLM scores for a different stock
        llm_scores = {
            '999999': (50.0, "Other stock")
        }
        
        results = scorer.calculate_batch_hybrid_scores(
            quant_results=[mock_quant_result],
            llm_scores=llm_scores
        )
        
        # 005930 has no LLM score -> use default 50.0
        assert len(results) == 1
        assert results[0].llm_score == 50.0
        assert results[0].llm_reason == "LLM 분석 없음"


# ============================================================================
# Tests: Candidate Selection
# ============================================================================

class TestSelectCandidates:
    """후보 선정 테스트"""

    def test_select_top_basic(self, scorer):
        """점수순 정렬 및 개수 제한"""
        from shared.hybrid_scoring.hybrid_scorer import HybridScoreResult
        
        # Create 5 results with different scores
        results = [
            HybridScoreResult('001', 'Stock1', 60, 60, 60, 0.6, 0.4),
            HybridScoreResult('002', 'Stock2', 80, 80, 80, 0.6, 0.4),
            HybridScoreResult('003', 'Stock3', 50, 50, 50, 0.6, 0.4),
            HybridScoreResult('004', 'Stock4', 90, 90, 90, 0.6, 0.4),
            HybridScoreResult('005', 'Stock5', 70, 70, 70, 0.6, 0.4),
        ]
        
        # Select top 3
        selected = scorer.select_top_candidates(results, max_count=3)
        
        assert len(selected) == 3
        assert selected[0].stock_code == '004'  # 90
        assert selected[1].stock_code == '002'  # 80
        assert selected[2].stock_code == '005'  # 70
        assert selected[0].final_rank == 1
        assert selected[2].final_rank == 3

    def test_select_empty(self, scorer):
        """빈 결과"""
        selected = scorer.select_top_candidates([], max_count=5)
        assert selected == []


# ============================================================================
# Tests: Summary Report
# ============================================================================

class TestSummaryReport:
    """리포트 생성 테스트"""

    def test_generate_report_format(self, scorer):
        """마크다운 포맷 확인"""
        from shared.hybrid_scoring.hybrid_scorer import HybridScoreResult
        
        results = [
            HybridScoreResult(
                '005930', 'Samsung', 80.0, 90.0, 84.0, 0.6, 0.4, 
                grade='A', llm_reason="Good", final_rank=1,
                condition_win_rate=0.7, condition_sample_count=50, condition_confidence="HIGH"
            )
        ]
        
        report = scorer.generate_summary_report(results)
        
        assert "Scout v1.0 Hybrid Scoring 분석 결과" in report
        assert "| 순위 | 종목명 | 등급 |" in report
        assert "Samsung" in report
        assert "005930" not in report # 005930 is not in table columns
        assert "A" in report  # Grade
        assert "84.0" in report  # Score
        
    def test_generate_report_empty(self, scorer):
        """빈 결과"""
        report = scorer.generate_summary_report([])
        assert "선정된 종목이 없습니다." in report


# ============================================================================
# Tests: Pipeline
# ============================================================================

class TestRunHybridScoringPipeline:
    """파이프라인 통합 테스트"""
    
    def test_pipeline_exists(self):
        """파이프라인 함수 존재"""
        from shared.hybrid_scoring.hybrid_scorer import run_hybrid_scoring_pipeline
        assert callable(run_hybrid_scoring_pipeline)

    def test_pipeline_full_flow(self):
        """전체 성공 흐름 테스트"""
        from shared.hybrid_scoring.hybrid_scorer import run_hybrid_scoring_pipeline, HybridScoreResult

        # 1. Setup Mock QuantScorer
        mock_quant_instance = MagicMock()
        
        # Return 2 candidates (one good, one bad)
        # Use MagicMock to avoid strict constructor signature and import errors
        q_res1 = MagicMock(stock_code='001', stock_name='GoodStock', total_score=80.0, 
                          momentum_score=20, quality_score=20, value_score=20, technical_score=20, news_stat_score=0, supply_demand_score=0, 
                          matched_conditions=[], condition_win_rate=0.7, condition_sample_count=50, condition_confidence='HIGH',
                          news_stat_sample_count=50,
                          short_term_score=80.0, short_term_grade='A', short_term_recommendation='BUY',
                          long_term_score=70.0, long_term_grade='B', long_term_recommendation='BUY',
                          recommended_holding_days=10, invalid_reason=None,
                          news_timing_signal="BUY_NOW", news_timing_reason="Good momentum", compound_bonus=10.0)
        # Ensure float type for formatting
        q_res1.total_score = 80.0
        
        q_res2 = MagicMock(stock_code='002', stock_name='BadStock', total_score=30.0, 
                          momentum_score=5, quality_score=5, value_score=10, technical_score=10, news_stat_score=0, supply_demand_score=0, 
                          matched_conditions=[], condition_win_rate=0.3, condition_sample_count=10, condition_confidence='LOW',
                          news_stat_sample_count=10,
                          short_term_score=30.0, short_term_grade='D', short_term_recommendation='SELL',
                          long_term_score=30.0, long_term_grade='D', long_term_recommendation='SELL',
                          recommended_holding_days=0, invalid_reason=None,
                          news_timing_signal="SELL_NEWS", news_timing_reason="Bad news", compound_bonus=0.0)
        q_res2.total_score = 30.0
        
        # calculate_total_quant_score is called for each candidate (iteratively)
        mock_quant_instance.calculate_total_quant_score.side_effect = [q_res1, q_res2]
        
        # filter_candidates returns filtered list
        mock_quant_instance.filter_candidates.return_value = [q_res1]

        # 2. Setup Mock LLM Analyzer
        mock_llm_analyzer = MagicMock()
        # analyze_with_context returns dict
        mock_llm_analyzer.analyze_with_context.return_value = {
            'score': 90.0, 'reason': "Excellent fundamentals"
        }

        # 3. Setup Mock DB Connection
        mock_db_conn = MagicMock()

        # 4. Run Pipeline
        candidates = [{'code': '001', 'name': 'GoodStock'}, {'code': '002', 'name': 'BadStock'}]
        
        final_results, report = run_hybrid_scoring_pipeline(
            candidates=candidates,
            quant_scorer=mock_quant_instance,
            llm_analyzer=mock_llm_analyzer,
            db_conn=mock_db_conn,
            market_regime='BULL',
            filter_cutoff=0.5,
            max_watchlist=5
        )

        # 5. Verify Steps
        # Quant calculation called twice (for each candidate)
        assert mock_quant_instance.calculate_total_quant_score.call_count == 2
        
        # Filter applied
        mock_quant_instance.filter_candidates.assert_called_once()
        
        # LLM called only for survivors (q_res1)
        mock_llm_analyzer.analyze_with_context.assert_called_once()
        
        # Check result
        assert len(final_results) == 1
        assert final_results[0].stock_code == '001'
        assert final_results[0].hybrid_score > 0
        assert "Scout v1.0" in report

    def test_pipeline_quant_failure(self):
        """Quant 계산 실패"""
        #candidates가 비어서 결과 없음
        from shared.hybrid_scoring.hybrid_scorer import run_hybrid_scoring_pipeline
        
        mock_quant_instance = MagicMock()
        
        results, report = run_hybrid_scoring_pipeline(
            candidates=[],
            quant_scorer=mock_quant_instance,
            llm_analyzer=MagicMock()
        )
        assert results == []

    def test_pipeline_no_survivors(self):
        """필터링 후 생존 종목 없음"""
        from shared.hybrid_scoring.hybrid_scorer import run_hybrid_scoring_pipeline
        
        mock_quant_instance = MagicMock()
        
        # Very low score
        q_res = MagicMock(stock_code='001', stock_name='BadStock', total_score=10.0,
                         news_stat_sample_count=0, condition_sample_count=0)
        q_res.total_score = 10.0
        
        mock_quant_instance.calculate_total_quant_score.return_value = q_res
        
        # Filter returns empty
        mock_quant_instance.filter_candidates.return_value = []
        
        results, report = run_hybrid_scoring_pipeline(
            candidates=[{'code': '001'}],
            quant_scorer=mock_quant_instance,
            llm_analyzer=MagicMock(),
            db_conn=MagicMock()
        )
        
        assert results == []
        assert "1차 필터링 통과 종목 없음" in report


class TestSafetyLockDetails:
    """안전장치 상세 로직 테스트"""

    def test_safety_lock_logging(self, scorer):
        """안전장치 로그 확인 (Capturing logs if needed, or just function)"""
        # 정량 70, LLM 100 (차이 30) -> 안전장치 발동
        # news_stat_sample_count를 int로 설정해야 함
        quant_result = MagicMock(
            total_score=70.0, 
            stock_code='LOGTEST', 
            stock_name='Test', 
            condition_win_rate=0.5, 
            condition_sample_count=10, 
            condition_confidence='MID',
            news_stat_sample_count=50  # 숫자 비교를 위해 추가
        )
        
        result = scorer.calculate_hybrid_score(
            quant_result=quant_result,
            llm_score=100.0
        )
        assert result.safety_lock_applied is True
        assert "정량 비중 상향" in result.safety_lock_reason

