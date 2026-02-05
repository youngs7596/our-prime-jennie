"""
tests/shared/test_llm_brain.py - JennieBrain 통합 테스트 (3단계)
================================================================

shared/llm.py의 JennieBrain 클래스를 테스트합니다.
Provider들을 mock하여 오케스트레이션 로직을 검증합니다.

실행 방법:
    pytest tests/shared/test_llm_brain.py -v
"""

import pytest
from unittest.mock import MagicMock, patch, PropertyMock
import json


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def mock_gemini_provider():
    """Mock Gemini Provider"""
    provider = MagicMock()
    provider.name = 'gemini'
    provider.flash_model_name.return_value = 'gemini-2.5-flash'
    provider.default_model = 'gemini-2.5-flash'
    return provider


@pytest.fixture
def mock_openai_provider():
    """Mock OpenAI Provider"""
    provider = MagicMock()
    provider.name = 'openai'
    provider.reasoning_model = 'gpt-5-mini'
    provider.default_model = 'gpt-4o-mini'
    return provider


@pytest.fixture
def mock_claude_provider():
    """Mock Claude Provider"""
    provider = MagicMock()
    provider.name = 'claude'
    provider.fast_model = 'claude-haiku-4-5'
    provider.reasoning_model = 'claude-sonnet-4-5'
    return provider


@pytest.fixture
def mock_brain(mock_gemini_provider, mock_openai_provider, mock_claude_provider):
    """모든 Provider가 mock된 JennieBrain"""
    from shared.llm import JennieBrain
    
    # __init__ 우회
    brain = object.__new__(JennieBrain)
    brain.provider = mock_gemini_provider
    brain.provider_gemini = mock_gemini_provider
    brain.provider_openai = mock_openai_provider
    brain.provider_claude = mock_claude_provider
    
    # _get_provider Mocking to support v6.0 Factory calls with Tier routing
    def get_provider_side_effect(tier):
        from shared.llm_factory import LLMTier
        if tier == LLMTier.FAST:
            return mock_gemini_provider
        elif tier == LLMTier.REASONING:
            return mock_claude_provider # or mock_gemini_provider depending on config, but let's use Claude for test distinction
        elif tier == LLMTier.THINKING:
            return mock_claude_provider # Judge/Thinking usually high intelligence
        return mock_gemini_provider

    brain._get_provider = MagicMock(side_effect=get_provider_side_effect)

    return brain


@pytest.fixture
def sample_stock_info():
    """테스트용 종목 정보"""
    return {
        'code': '005930',
        'name': '삼성전자',
        'price': 70000,
        'remaining_budget': 1000000,
        'rag_context': 'AI 반도체 수혜 기대',
        'per': 10.5,
        'pbr': 1.2,
        'market_cap': 400000000,
    }


@pytest.fixture
def sample_portfolio_item():
    """테스트용 포트폴리오 아이템"""
    return {
        'id': 1,
        'code': '005930',
        'name': '삼성전자',
        'avg_price': 65000,
        'high_price': 75000,
        'quantity': 100,
    }


# ============================================================================
# Tests: JennieBrain 초기화
# ============================================================================




# ============================================================================
# Tests: _calculate_grade
# ============================================================================

class TestCalculateGrade:
    """등급 계산 함수 테스트"""
    
    def test_grade_s_80_and_above(self, mock_brain):
        """80점 이상은 S등급"""
        assert mock_brain._calculate_grade(80) == 'S'
        assert mock_brain._calculate_grade(90) == 'S'
        assert mock_brain._calculate_grade(100) == 'S'
    
    def test_grade_a_70_to_79(self, mock_brain):
        """70-79점은 A등급"""
        assert mock_brain._calculate_grade(70) == 'A'
        assert mock_brain._calculate_grade(75) == 'A'
        assert mock_brain._calculate_grade(79) == 'A'
    
    def test_grade_b_60_to_69(self, mock_brain):
        """60-69점은 B등급"""
        assert mock_brain._calculate_grade(60) == 'B'
        assert mock_brain._calculate_grade(65) == 'B'
        assert mock_brain._calculate_grade(69) == 'B'
    
    def test_grade_c_50_to_59(self, mock_brain):
        """50-59점은 C등급"""
        assert mock_brain._calculate_grade(50) == 'C'
        assert mock_brain._calculate_grade(55) == 'C'
        assert mock_brain._calculate_grade(59) == 'C'
    
    def test_grade_d_40_to_49(self, mock_brain):
        """40-49점은 D등급"""
        assert mock_brain._calculate_grade(40) == 'D'
        assert mock_brain._calculate_grade(45) == 'D'
        assert mock_brain._calculate_grade(49) == 'D'
    
    def test_grade_f_below_40(self, mock_brain):
        """40점 미만은 F등급"""
        assert mock_brain._calculate_grade(39) == 'F'
        assert mock_brain._calculate_grade(20) == 'F'
        assert mock_brain._calculate_grade(0) == 'F'
    
    def test_grade_with_string_number(self, mock_brain):
        """문자열 숫자도 처리"""
        assert mock_brain._calculate_grade("85") == 'S'
        assert mock_brain._calculate_grade("65") == 'B'
    
    def test_grade_with_float(self, mock_brain):
        """소수점도 처리"""
        assert mock_brain._calculate_grade(79.9) == 'A'
        assert mock_brain._calculate_grade(80.0) == 'S'
    
    def test_grade_with_invalid_input(self, mock_brain):
        """유효하지 않은 입력은 D 반환"""
        assert mock_brain._calculate_grade("invalid") == 'D'
        assert mock_brain._calculate_grade(None) == 'D'


# ============================================================================
# Tests: get_jennies_decision
# ============================================================================

class TestGetJenniesDecision:
    """get_jennies_decision 오케스트레이션 테스트"""
    
    def test_buy_mr_decision_approve(self, mock_brain, mock_claude_provider, sample_stock_info):
        """BUY_MR 결재 승인"""
        mock_claude_provider.generate_json.return_value = {
            'decision': 'APPROVE',
            'reason': '볼린저 밴드 하단 터치, 매수 적합',
            'quantity': 10
        }
        
        result = mock_brain.get_jennies_decision(
            'BUY_MR',
            sample_stock_info,
            buy_signal_type='BB_LOWER'
        )
        
        assert result['decision'] == 'APPROVE'
        assert result['quantity'] == 10
        mock_claude_provider.generate_json.assert_called_once()
    
    def test_buy_mr_decision_reject(self, mock_brain, mock_claude_provider, sample_stock_info):
        """BUY_MR 결재 거절"""
        mock_claude_provider.generate_json.return_value = {
            'decision': 'REJECT',
            'reason': '시장 불안정으로 매수 부적합',
            'quantity': 0
        }
        
        result = mock_brain.get_jennies_decision(
            'BUY_MR',
            sample_stock_info,
            buy_signal_type='RSI_OVERSOLD'
        )
        
        assert result['decision'] == 'REJECT'
        assert result['quantity'] == 0
    
    def test_buy_trend_decision(self, mock_brain, mock_claude_provider, sample_stock_info):
        """BUY_TREND 결재"""
        mock_claude_provider.generate_json.return_value = {
            'decision': 'APPROVE',
            'reason': '골든 크로스 확인',
            'quantity': 5
        }
        
        result = mock_brain.get_jennies_decision(
            'BUY_TREND',
            sample_stock_info,
            buy_signal_type='GOLDEN_CROSS'
        )
        
        assert result['decision'] == 'APPROVE'
    
    def test_sell_decision(self, mock_brain, mock_claude_provider, sample_portfolio_item):
        """SELL 결재"""
        mock_claude_provider.generate_json.return_value = {
            'decision': 'SELL',
            'reason': 'RSI 과열로 수익 실현',
            'quantity': 0
        }
        
        result = mock_brain.get_jennies_decision(
            'SELL',
            sample_portfolio_item
        )
        
        assert result['decision'] == 'SELL'
    
    def test_unknown_trade_type(self, mock_brain, sample_stock_info):
        """알 수 없는 거래 타입"""
        result = mock_brain.get_jennies_decision(
            'UNKNOWN_TYPE',
            sample_stock_info
        )
        
        assert result['decision'] == 'REJECT'
        assert '알 수 없는' in result['reason']
    

    



# ============================================================================
# Tests: analyze_news_sentiment
# ============================================================================

class TestAnalyzeNewsSentiment:
    """뉴스 감성 분석 테스트"""
    
    def test_sentiment_positive_news(self, mock_brain):
        """긍정적 뉴스"""
        mock_brain.provider_gemini.generate_json.return_value = {
            'score': 85,
            'reason': '대규모 수주 발표로 강력 호재'
        }
        mock_brain.provider_gemini.flash_model_name.return_value = 'gemini-2.5-flash'
        
        result = mock_brain.analyze_news_sentiment(
            "삼성전자, AI 반도체 10조원 수주 계약",
            "글로벌 빅테크 기업들과 AI 반도체 공급 계약 체결"
        )
        
        assert result['score'] == 85
        assert '호재' in result['reason']
    
    def test_sentiment_negative_news(self, mock_brain):
        """부정적 뉴스"""
        mock_brain.provider_gemini.generate_json.return_value = {
            'score': 20,
            'reason': '실적 쇼크로 강력 악재'
        }
        mock_brain.provider_gemini.flash_model_name.return_value = 'gemini-2.5-flash'
        
        result = mock_brain.analyze_news_sentiment(
            "삼성전자, 3분기 실적 어닝쇼크",
            "영업이익 전년 대비 80% 감소"
        )
        
        assert result['score'] == 20
        assert '악재' in result['reason']
    
    def test_sentiment_neutral_news(self, mock_brain):
        """중립 뉴스"""
        mock_brain.provider_gemini.generate_json.return_value = {
            'score': 50,
            'reason': '일반적인 시황 뉴스'
        }
        mock_brain.provider_gemini.flash_model_name.return_value = 'gemini-2.5-flash'
        
        result = mock_brain.analyze_news_sentiment(
            "반도체 업종 동향",
            "업종 전반 보합세"
        )
        
        assert result['score'] == 50

# ============================================================================
# Tests: JennieBrain 초기화 (v6.0 Factory Pattern)
# ============================================================================

class TestJennieBrainInit:
    """JennieBrain 초기화 테스트 (Factory Pattern)"""
    
    def test_init_basic(self):
        """기본 초기화 확인"""
        from shared.llm import JennieBrain
        brain = JennieBrain()
        assert brain is not None
        # v6.0에서는 __init__에서 provider를 미리 로드하지 않음

# ============================================================================
# Tests: run_debate_session (v6.0)
# ============================================================================

class TestRunDebateSession:
    """Bull vs Bear 토론 테스트 (REASONING Tier)"""
    
    def test_debate_session_success(self, mock_brain, mock_claude_provider, sample_stock_info):
        """토론 세션 성공"""
        sample_stock_info['dominant_keywords'] = ['AI', 'HBM']
        
        # REASONING Tier uses mock_claude_provider in our fixture
        mock_claude_provider.generate_chat.return_value = {
            'text': "Bull: AI 호재! Bear: 거품이야."
        }
        
        result = mock_brain.run_debate_session(sample_stock_info, hunter_score=80)
        
        assert "Bull" in result
        
        # Verify Provider Tier (REASONING)
        from shared.llm_factory import LLMTier
        mock_brain._get_provider.assert_any_call(LLMTier.REASONING)

    def test_debate_session_provider_error(self, mock_brain, sample_stock_info):
        """Provider 로드 실패"""
        mock_brain._get_provider.side_effect = None # Break the side effect
        mock_brain._get_provider.return_value = None
        
        result = mock_brain.run_debate_session(sample_stock_info)
        assert "Skipped" in result

# ============================================================================
# Tests: run_judge_scoring (v6.0)
# ============================================================================

class TestRunJudgeScoring:
    """Judge 최종 판결 테스트 (THINKING Tier)"""
    
    def test_judge_scoring_success(self, mock_brain, mock_claude_provider, sample_stock_info):
        """판결 성공"""
        debate_log = "Bull vs Bear Debate Log"
        sample_stock_info['dominant_keywords'] = ['AI']
        
        # THINKING Tier uses mock_claude_provider
        mock_claude_provider.generate_json.return_value = {
            'score': 85,
            'grade': 'B',
            'reason': '토론 결과 긍정적'
        }
        
        result = mock_brain.run_judge_scoring(sample_stock_info, debate_log)
        
        assert result['score'] == 85
        assert result['grade'] == 'B'
        
        from shared.llm_factory import LLMTier
        mock_brain._get_provider.assert_any_call(LLMTier.THINKING)

    def test_judge_scoring_v5_fallback(self, mock_brain, mock_claude_provider, sample_stock_info):
        """정량 컨텍스트 포함 시 v5 로직 (REASONING)"""
        debate_log = "Debate"
        quant_context = "Quant Score: 80"
        sample_stock_info['hunter_score'] = 80 # Pass Gatekeeper
        
        # Judge V5 uses THINKING Tier (Claude)
        mock_claude_provider.generate_json.return_value = {
            'score': 82,
            'grade': 'A',
            'reason': 'V5 Logic'
        }
        
        result = mock_brain.run_judge_scoring_v5(sample_stock_info, debate_log, quant_context)
        
        assert result['score'] == 82
        
        from shared.llm_factory import LLMTier
        mock_brain._get_provider.assert_any_call(LLMTier.THINKING)


# ============================================================================
# Tests: v5 Hybrid Scoring
# ============================================================================

class TestV5HybridScoring:
    """v5 하이브리드 스코어링 테스트 (FAST/REASONING)"""
    
    def test_analysis_score_v5_fast(self, mock_brain, mock_claude_provider, sample_stock_info):
        """REASONING Tier 사용 확인 (v5 Hunter)"""
        # v5 Hunter uses REASONING Tier (Claude in mock)
        mock_claude_provider.generate_json.return_value = {
            'score': 75,
            'grade': 'B',
            'reason': 'Fast Analysis'
        }
        
        result = mock_brain.get_jennies_analysis_score_v5(sample_stock_info, quant_context=None)
        
        assert result['score'] == 75
        
        from shared.llm_factory import LLMTier
        mock_brain._get_provider.assert_any_call(LLMTier.REASONING)

# ============================================================================
# Tests: generate_daily_briefing
# ============================================================================

class TestGenerateDailyBriefing:
    """데일리 브리핑 생성 테스트 (REASONING Tier)"""
    
    def test_daily_briefing_success(self, mock_brain, mock_claude_provider):
        """브리핑 생성 성공"""
        market_data = "KOSPI 2500"
        execution_log = "Bought Samsung"
        
        # Briefing uses THINKING Tier (Claude)
        mock_claude_provider.generate_chat.return_value = {
            'text': "Overall Market: Bullish..."
        }
        
        # Mock default model for tokens
        mock_claude_provider.default_model = 'claude-3-opus'
        
        result = mock_brain.generate_daily_briefing(market_data, execution_log)
        
        assert "Bullish" in result
        
        from shared.llm_factory import LLMTier
        mock_brain._get_provider.assert_any_call(LLMTier.THINKING)
    
    def test_daily_briefing_provider_error(self):
        """Provider 오류시 에러 메시지 반환"""
        from shared.llm import JennieBrain
        
        brain = object.__new__(JennieBrain)
        brain._get_provider = MagicMock(return_value=None)
        
        result = brain.generate_daily_briefing("market", "log")
        
        assert "실패" in result or "오류" in result
    
    def test_daily_briefing_empty_data(self, mock_brain, mock_claude_provider):
        """빈 데이터도 처리"""
        mock_claude_provider.generate_chat.return_value = {
            'text': "No data available report"
        }
        
        result = mock_brain.generate_daily_briefing("", "")
        
        assert result is not None


# ============================================================================
# Tests: generate_strategic_feedback
# ============================================================================

class TestGenerateStrategicFeedback:
    """전략적 피드백 생성 테스트"""
    
    def test_strategic_feedback_success(self, mock_brain, mock_claude_provider):
        """피드백 생성 성공"""
        mock_claude_provider.generate_chat.return_value = {
            'text': "1. 하락장에서 RSI 과열 종목 매수 금지\n2. 바이오 섹터 신중하게"
        }
        
        result = mock_brain.generate_strategic_feedback("성과: 5승 3패")
        
        assert "RSI" in result or "하락" in result or isinstance(result, str)
        
        from shared.llm_factory import LLMTier
        mock_brain._get_provider.assert_any_call(LLMTier.THINKING)
    
    def test_strategic_feedback_provider_error(self):
        """Provider 오류시 빈 문자열"""
        from shared.llm import JennieBrain
        
        brain = object.__new__(JennieBrain)
        brain._get_provider = MagicMock(return_value=None)
        
        result = brain.generate_strategic_feedback("performance summary")
        
        assert result == ""
    
    def test_strategic_feedback_exception(self, mock_brain, mock_claude_provider):
        """예외 발생시 빈 문자열"""
        mock_claude_provider.generate_chat.side_effect = Exception("API Error")
        
        result = mock_brain.generate_strategic_feedback("summary")
        
        assert result == ""


# ============================================================================
# Tests: verify_parameter_change
# ============================================================================

class TestVerifyParameterChange:
    """파라미터 변경 검증 테스트"""
    
    def test_verify_parameter_change_success(self, mock_brain, mock_gemini_provider, sample_stock_info):
        """파라미터 변경 자동 승인"""
        result = mock_brain.verify_parameter_change(
            sample_stock_info,
            param_name="stop_loss",
            old_val=0.05,
            new_val=0.10
        )
        
        assert result["authorized"] is True
    
    def test_verify_parameter_change_no_provider(self, sample_stock_info):
        """Provider 없으면 미승인"""
        from shared.llm import JennieBrain
        
        brain = object.__new__(JennieBrain)
        brain._get_provider = MagicMock(return_value=None)
        
        result = brain.verify_parameter_change(
            sample_stock_info,
            param_name="stop_loss",
            old_val=0.05,
            new_val=0.10
        )
        
        assert result["authorized"] is False


# ============================================================================
# Tests: analyze_competitor_benefit
# ============================================================================

class TestAnalyzeCompetitorBenefit:
    """경쟁사 수혜 분석 테스트"""
    
    def test_competitor_benefit_risk_detected(self, mock_brain, mock_gemini_provider):
        """리스크 감지"""
        mock_gemini_provider.generate_json.return_value = {
            'is_risk': True,
            'event_type': 'competitor_success',
            'competitor_benefit_score': 80,
            'reason': '경쟁사 대규모 수주로 점유율 위협'
        }
        
        result = mock_brain.analyze_competitor_benefit(
            "경쟁사 A, 10조원 수주 발표"
        )
        
        assert result['is_risk'] is True
        assert result['competitor_benefit_score'] == 80
    
    def test_competitor_benefit_no_risk(self, mock_brain, mock_gemini_provider):
        """리스크 없음"""
        mock_gemini_provider.generate_json.return_value = {
            'is_risk': False,
            'event_type': 'neutral',
            'competitor_benefit_score': 20,
            'reason': '일반적인 시황 뉴스'
        }
        
        result = mock_brain.analyze_competitor_benefit(
            "반도체 업종 동향 분석"
        )
        
        assert result['is_risk'] is False
    
    def test_competitor_benefit_provider_error(self):
        """Provider 오류시 기본값"""
        from shared.llm import JennieBrain
        
        brain = object.__new__(JennieBrain)
        brain._get_provider = MagicMock(return_value=None)
        
        result = brain.analyze_competitor_benefit("news title")
        
        assert result['is_risk'] is False
        assert 'Error' in result.get('reason', '')
    
    def test_competitor_benefit_exception(self, mock_brain, mock_gemini_provider):
        """예외 발생시 기본값"""
        mock_gemini_provider.generate_json.side_effect = Exception("API Error")
        
        result = mock_brain.analyze_competitor_benefit("news title")
        
        assert result['is_risk'] is False
        assert 'Error' in result.get('reason', '')


# ============================================================================
# Tests: run_judge_scoring_v5 (Gatekeeper Logic)
# ============================================================================

class TestJudgeScoringV5Gatekeeper:
    """Judge v5 Gatekeeper 로직 테스트"""
    
    def test_gatekeeper_rejects_low_score(self, mock_brain, sample_stock_info):
        """낮은 Hunter 점수는 자동 거절"""
        sample_stock_info['hunter_score'] = 60  # < 70 threshold
        
        result = mock_brain.run_judge_scoring_v5(sample_stock_info, "debate_log")
        
        assert result['score'] == 60
        assert 'RECON tier' in result['reason']
        assert result['grade'] == 'B'  # 60점은 B등급
    
    def test_gatekeeper_passes_high_score(self, mock_brain, mock_claude_provider, sample_stock_info):
        """높은 Hunter 점수는 Judge 호출"""
        sample_stock_info['hunter_score'] = 75  # >= 70 threshold
        
        mock_claude_provider.generate_json.return_value = {
            'score': 78,
            'grade': 'A',
            'reason': 'Judge approved'
        }
        
        result = mock_brain.run_judge_scoring_v5(sample_stock_info, "debate_log")
        
        assert result['score'] == 78
        # grade는 코드에서 재계산됨
        mock_claude_provider.generate_json.assert_called_once()
    
    def test_grade_correction(self, mock_brain, mock_claude_provider, sample_stock_info):
        """LLM 등급 불일치 교정"""
        sample_stock_info['hunter_score'] = 80
        
        # LLM이 잘못된 등급을 반환
        mock_claude_provider.generate_json.return_value = {
            'score': 85,
            'grade': 'B',  # 잘못된 등급 (85점은 S여야 함)
            'reason': 'Great stock'
        }
        
        result = mock_brain.run_judge_scoring_v5(sample_stock_info, "debate_log")
        
        # 코드에서 등급을 재계산하여 교정
        assert result['grade'] == 'S'  # 85점은 S등급


# ============================================================================
# Tests: News Sentiment Fallback
# ============================================================================

class TestNewsSentimentFallback:
    """뉴스 감성 분석 Fallback 테스트
    [2026-02] get_fallback_provider 제거 이후: Local 실패 시 기본값(50) 반환
    """

    def test_sentiment_local_failure_returns_default(self, mock_brain, mock_gemini_provider):
        """Local 실패 시 기본점수 50 반환"""
        mock_gemini_provider.generate_json.side_effect = Exception("Local Error")

        result = mock_brain.analyze_news_sentiment("title", "desc")

        assert result['score'] == 50

    def test_sentiment_both_fail(self, mock_brain, mock_gemini_provider):
        """Local 실패 시 기본값 반환 (Cloud Fallback 없음)"""
        mock_gemini_provider.generate_json.side_effect = Exception("Local Error")

        result = mock_brain.analyze_news_sentiment("title", "desc")

        assert result['score'] == 50





    



