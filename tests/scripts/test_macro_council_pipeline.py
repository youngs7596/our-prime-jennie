"""
tests/scripts/test_macro_council_pipeline.py
---------------------------------------------
Macro Council 구조화 JSON 파이프라인 테스트.
"""

import json
import sys
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# 프로젝트 루트를 sys.path에 추가
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ==============================================================================
# 테스트 픽스처
# ==============================================================================

SAMPLE_STRATEGIST_OUTPUT = {
    "overall_sentiment": "neutral_to_bullish",
    "sentiment_score": 62,
    "regime_hint": "KOSDAQ_Momentum",
    "sector_signals": {"반도체/IT": "bullish", "자동차/운송": "bearish", "바이오/헬스케어": "neutral"},
    "risk_factors": ["미중 기술 분쟁 격화", "원화 약세 지속"],
    "opportunity_factors": ["AI 반도체 수요 증가", "KOSDAQ 실적 개선"],
    "investor_flow_analysis": "외국인 KOSPI 순매도 지속, 기관 반도체 중심 순매수",
}

SAMPLE_RISK_OUTPUT = {
    "risk_assessment": {
        "agree_with_sentiment": True,
        "adjusted_sentiment_score": 58,
        "adjustment_reason": "원화 약세 리스크 반영하여 4점 하향",
    },
    "political_risk_level": "medium",
    "political_risk_summary": "트럼프 행정부 대중 반도체 규제 확대 가능성이 한국 반도체 수출에 영향",
    "additional_risk_factors": ["지정학 리스크: 북한 미사일 발사 가능성"],
    "position_size_pct": 90,
    "stop_loss_adjust_pct": 110,
    "risk_reasoning": "원화 약세와 정치 리스크 감안 시 포지션 소폭 축소 권장. 변동성 확대 대비 손절폭 확대.",
}

SAMPLE_JUDGE_OUTPUT = {
    "final_sentiment": "neutral_to_bullish",
    "final_sentiment_score": 60,
    "final_regime_hint": "KOSDAQ_Momentum",
    "strategies_to_favor": ["MOMENTUM_CONTINUATION", "RECON_BULL_ENTRY"],
    "strategies_to_avoid": ["SHORT_TERM_HIGH_BREAKOUT"],
    "sectors_to_favor": ["반도체/IT", "바이오/헬스케어"],
    "sectors_to_avoid": ["자동차/운송"],
    "final_position_size_pct": 90,
    "final_stop_loss_adjust_pct": 110,
    "trading_reasoning": "반도체 중심 모멘텀 유지되나 정치 리스크 감안 포지션 소폭 축소. 변동성 확대 대비.",
    "council_consensus": "agree",
}


# ==============================================================================
# merge_council_outputs 테스트
# ==============================================================================

class TestMergeCouncilOutputs:
    """merge_council_outputs 함수 테스트"""

    def test_basic_merge(self):
        """기본 병합이 정상적으로 동작하는지 확인"""
        from scripts.run_macro_council import merge_council_outputs

        result = merge_council_outputs(
            SAMPLE_STRATEGIST_OUTPUT,
            SAMPLE_RISK_OUTPUT,
            SAMPLE_JUDGE_OUTPUT,
        )

        # 수석심판 결정이 최종
        assert result["sentiment"] == "neutral_to_bullish"
        assert result["sentiment_score"] == 60
        assert result["regime_hint"] == "KOSDAQ_Momentum"

        # 전략가 원본 유지
        assert result["sector_signals"]["반도체/IT"] == "bullish"
        assert "미중 기술 분쟁 격화" in result["risk_factors"]
        assert "AI 반도체 수요 증가" in result["opportunity_factors"]

        # 리스크분석가 정치 리스크
        assert result["political_risk_level"] == "medium"
        assert "트럼프" in result["political_risk_summary"]

        # 추가 리스크 병합
        assert any("북한" in r for r in result["risk_factors"])

    def test_strategy_validation(self):
        """유효하지 않은 전략이 필터링되는지 확인"""
        from scripts.run_macro_council import merge_council_outputs

        bad_judge = dict(SAMPLE_JUDGE_OUTPUT)
        bad_judge["strategies_to_favor"] = ["MOMENTUM_CONTINUATION", "INVALID_STRATEGY"]

        result = merge_council_outputs(
            SAMPLE_STRATEGIST_OUTPUT, SAMPLE_RISK_OUTPUT, bad_judge,
        )

        assert "MOMENTUM_CONTINUATION" in result["strategies_to_favor"]
        assert "INVALID_STRATEGY" not in result["strategies_to_favor"]

    def test_sector_validation(self):
        """유효하지 않은 섹터가 필터링되는지 확인"""
        from scripts.run_macro_council import merge_council_outputs

        bad_judge = dict(SAMPLE_JUDGE_OUTPUT)
        bad_judge["sectors_to_favor"] = ["반도체/IT", "존재하지않는섹터"]

        result = merge_council_outputs(
            SAMPLE_STRATEGIST_OUTPUT, SAMPLE_RISK_OUTPUT, bad_judge,
        )

        assert "반도체/IT" in result["sectors_to_favor"]
        assert "존재하지않는섹터" not in result["sectors_to_favor"]

    def test_score_clamping(self):
        """점수 범위 클램핑 테스트"""
        from scripts.run_macro_council import merge_council_outputs

        extreme_judge = dict(SAMPLE_JUDGE_OUTPUT)
        extreme_judge["final_sentiment_score"] = 150  # 범위 초과
        extreme_judge["final_position_size_pct"] = 200  # 범위 초과
        extreme_judge["final_stop_loss_adjust_pct"] = 30  # 범위 미달

        result = merge_council_outputs(
            SAMPLE_STRATEGIST_OUTPUT, SAMPLE_RISK_OUTPUT, extreme_judge,
        )

        assert result["sentiment_score"] == 100  # clamped to 100
        assert result["position_size_pct"] == 130  # clamped to 130
        assert result["stop_loss_adjust_pct"] == 80  # clamped to 80

    def test_political_risk_validation(self):
        """잘못된 political_risk_level이 low로 폴백하는지 확인"""
        from scripts.run_macro_council import merge_council_outputs

        bad_risk = dict(SAMPLE_RISK_OUTPUT)
        bad_risk["political_risk_level"] = "invalid_level"

        result = merge_council_outputs(
            SAMPLE_STRATEGIST_OUTPUT, bad_risk, SAMPLE_JUDGE_OUTPUT,
        )

        assert result["political_risk_level"] == "low"

    def test_regime_hint_truncation(self):
        """50자 초과 regime_hint가 잘리는지 확인 (DB VARCHAR(200) 안전장치)"""
        from scripts.run_macro_council import merge_council_outputs

        long_judge = dict(SAMPLE_JUDGE_OUTPUT)
        long_judge["final_regime_hint"] = "매크로 이벤트로 변동성이 큰 가운데 기관 수급이 하단을 방어하되 개인 자금 이탈로 상단도 제한되는 변동성 혼재 레짐"

        result = merge_council_outputs(
            SAMPLE_STRATEGIST_OUTPUT, SAMPLE_RISK_OUTPUT, long_judge,
        )

        assert len(result["regime_hint"]) <= 50
        assert result["regime_hint"].endswith("...")

    def test_regime_hint_short_not_truncated(self):
        """50자 이하 regime_hint는 그대로 유지되는지 확인"""
        from scripts.run_macro_council import merge_council_outputs

        result = merge_council_outputs(
            SAMPLE_STRATEGIST_OUTPUT, SAMPLE_RISK_OUTPUT, SAMPLE_JUDGE_OUTPUT,
        )

        assert result["regime_hint"] == "KOSDAQ_Momentum"

    def test_raw_council_output_included(self):
        """원본 JSON이 디버깅용으로 포함되는지 확인"""
        from scripts.run_macro_council import merge_council_outputs

        result = merge_council_outputs(
            SAMPLE_STRATEGIST_OUTPUT, SAMPLE_RISK_OUTPUT, SAMPLE_JUDGE_OUTPUT,
        )

        assert "raw_council_output" in result
        assert "strategist" in result["raw_council_output"]
        assert "risk_analyst" in result["raw_council_output"]
        assert "chief_judge" in result["raw_council_output"]


# ==============================================================================
# _fallback_judge_output 테스트
# ==============================================================================

class TestFallbackJudgeOutput:
    """수석심판 실패 시 폴백 로직 테스트"""

    def test_fallback_uses_strategist_sentiment(self):
        from scripts.run_macro_council import _fallback_judge_output

        result = _fallback_judge_output(SAMPLE_STRATEGIST_OUTPUT, SAMPLE_RISK_OUTPUT)

        assert result["final_sentiment"] == "neutral_to_bullish"
        assert result["final_sentiment_score"] == 58  # 리스크분석가 조정 점수
        assert result["council_consensus"] == "partial_disagree"

    def test_fallback_uses_risk_position(self):
        from scripts.run_macro_council import _fallback_judge_output

        result = _fallback_judge_output(SAMPLE_STRATEGIST_OUTPUT, SAMPLE_RISK_OUTPUT)

        assert result["final_position_size_pct"] == 90
        assert result["final_stop_loss_adjust_pct"] == 110


# ==============================================================================
# _build_context_text 테스트
# ==============================================================================

class TestBuildContextText:
    """컨텍스트 빌더 테스트"""

    def test_basic_context(self):
        from scripts.run_macro_council import _build_context_text

        result = _build_context_text("테스트 브리핑 메시지")
        assert "테스트 브리핑 메시지" in result

    def test_with_global_snapshot(self):
        from scripts.run_macro_council import _build_context_text

        snapshot = {
            "fed_rate": 5.25,
            "vix": 18.5,
            "vix_regime": "normal",
            "usd_krw": 1380,
            "kospi_index": 2650,
            "kospi_change_pct": 0.5,
            "kosdaq_index": 850,
            "kosdaq_change_pct": -0.3,
            "krw_pressure": "weak",
            "is_risk_off": False,
            "treasury_10y": 4.5,
            "us_cpi_yoy": 3.2,
            "us_unemployment": 3.8,
            "dxy_index": 104.5,
            "bok_rate": 3.5,
            "rate_differential": 1.75,
            "kospi_foreign_net": -500,
            "kosdaq_foreign_net": 200,
            "kospi_institutional_net": 300,
            "kospi_retail_net": 100,
            "global_news_sentiment": "neutral",
            "korea_news_sentiment": "positive",
            "completeness_score": 0.85,
            "data_sources": ["fred", "investing.com"],
        }

        result = _build_context_text("브리핑", global_snapshot=snapshot)
        assert "Fed Rate: 5.25%" in result
        assert "VIX: 18.5" in result
        assert "USD/KRW: 1380" in result

    def test_with_political_news(self):
        from scripts.run_macro_council import _build_context_text

        news = [
            {"title": "트럼프 관세 발표", "source": "Reuters", "category": "trade"},
            {"title": "북한 미사일 발사", "source": "YNA", "category": "geopolitics"},
        ]

        result = _build_context_text("브리핑", political_news=news)
        assert "트럼프 관세 발표" in result
        assert "북한 미사일 발사" in result
        assert "Reuters" in result


# ==============================================================================
# _load_prompt 테스트
# ==============================================================================

class TestLoadPrompt:
    """프롬프트 파일 로드 테스트"""

    def test_strategist_prompt_exists(self):
        from scripts.run_macro_council import _load_prompt

        prompt = _load_prompt("macro_strategist.txt")
        assert "전략가" in prompt or "매크로" in prompt

    def test_risk_analyst_prompt_exists(self):
        from scripts.run_macro_council import _load_prompt

        prompt = _load_prompt("macro_risk_analyst.txt")
        assert "리스크" in prompt

    def test_chief_judge_prompt_exists(self):
        from scripts.run_macro_council import _load_prompt

        prompt = _load_prompt("macro_chief_judge.txt")
        assert "심판" in prompt

    def test_prompts_contain_strategy_list(self):
        """수석심판 프롬프트에 시스템 전략 목록이 포함되는지 확인"""
        from scripts.run_macro_council import _load_prompt

        prompt = _load_prompt("macro_chief_judge.txt")
        assert "GOLDEN_CROSS" in prompt
        assert "VCP_BREAKOUT" in prompt
        assert "INSTITUTIONAL_ENTRY" in prompt

    def test_prompts_contain_sector_list(self):
        """전략가/수석심판 프롬프트에 섹터 대분류가 포함되는지 확인"""
        from scripts.run_macro_council import _load_prompt

        for fname in ("macro_strategist.txt", "macro_chief_judge.txt"):
            prompt = _load_prompt(fname)
            assert "반도체/IT" in prompt, f"{fname}에 섹터 목록 없음"
            assert "바이오/헬스케어" in prompt, f"{fname}에 섹터 목록 없음"


# ==============================================================================
# 스키마 상수 테스트
# ==============================================================================

class TestSchemaConstants:
    """llm_constants.py의 스키마 검증"""

    def test_strategist_schema_required_fields(self):
        from shared.llm_constants import MACRO_STRATEGIST_SCHEMA

        required = MACRO_STRATEGIST_SCHEMA["required"]
        assert "overall_sentiment" in required
        assert "sentiment_score" in required
        assert "risk_factors" in required
        assert "opportunity_factors" in required
        assert "investor_flow_analysis" in required
        assert "sector_signals" in required
        # 개별 종목/테마는 매크로 분석에서 제외
        assert "key_themes" not in required
        assert "key_stocks" not in required

    def test_risk_analyst_schema_required_fields(self):
        from shared.llm_constants import MACRO_RISK_ANALYST_SCHEMA

        required = MACRO_RISK_ANALYST_SCHEMA["required"]
        assert "risk_assessment" in required
        assert "political_risk_level" in required
        assert "position_size_pct" in required

    def test_chief_judge_schema_required_fields(self):
        from shared.llm_constants import MACRO_CHIEF_JUDGE_SCHEMA

        required = MACRO_CHIEF_JUDGE_SCHEMA["required"]
        assert "final_sentiment" in required
        assert "strategies_to_favor" in required
        assert "sectors_to_favor" in required
        assert "council_consensus" in required

    def test_trading_strategies_list(self):
        from shared.llm_constants import TRADING_STRATEGIES

        assert len(TRADING_STRATEGIES) == 10
        assert "GOLDEN_CROSS" in TRADING_STRATEGIES
        assert "INSTITUTIONAL_ENTRY" in TRADING_STRATEGIES

    def test_sector_groups_list(self):
        from shared.llm_constants import SECTOR_GROUPS

        assert len(SECTOR_GROUPS) == 14
        assert "반도체/IT" in SECTOR_GROUPS
        assert "기타" in SECTOR_GROUPS


# ==============================================================================
# 통합 파이프라인 테스트 (모킹)
# ==============================================================================

class TestStructuredCouncilPipeline:
    """run_structured_council 통합 테스트 (LLM 호출 모킹)"""

    @patch("scripts.run_macro_council._init_providers")
    def test_full_pipeline_success(self, mock_init):
        """3단계 모두 성공하는 정상 케이스"""
        from scripts.run_macro_council import run_structured_council

        mock_deepseek = MagicMock()
        # 동일 프로바이더: Step 1 → 전략가, Step 2 → 리스크분석가
        mock_deepseek.generate_json.side_effect = [
            SAMPLE_STRATEGIST_OUTPUT,  # Step 1
            SAMPLE_RISK_OUTPUT,        # Step 2
        ]

        mock_judge = MagicMock()
        mock_judge.generate_json_with_thinking.return_value = SAMPLE_JUDGE_OUTPUT

        mock_init.return_value = (mock_deepseek, mock_deepseek, mock_judge)

        result = run_structured_council("테스트 컨텍스트")

        assert "error" not in result
        assert result["sentiment"] == "neutral_to_bullish"
        assert result["sentiment_score"] == 60
        assert result["political_risk_level"] == "medium"
        assert "cost_usd" in result
        assert result["cost_usd"] > 0

    @patch("scripts.run_macro_council._init_providers")
    def test_strategist_fallback_to_claude(self, mock_init):
        """전략가(DeepSeek) 실패 시 Claude Opus로 폴백"""
        from scripts.run_macro_council import run_structured_council

        mock_strategist = MagicMock()
        mock_strategist.generate_json.side_effect = Exception("DeepSeek API 장애")

        mock_risk = mock_strategist

        mock_judge = MagicMock()
        mock_judge.generate_json_with_thinking.side_effect = [
            SAMPLE_STRATEGIST_OUTPUT,  # 전략가 fallback
            SAMPLE_JUDGE_OUTPUT,       # 수석심판
        ]

        mock_init.return_value = (mock_strategist, mock_risk, mock_judge)

        result = run_structured_council("테스트 컨텍스트")

        assert "error" not in result
        # Claude fallback이 전략가 역할을 수행했으므로 정상 결과
        assert result["sentiment"] == "neutral_to_bullish"

    @patch("scripts.run_macro_council._init_providers")
    def test_risk_analyst_failure_uses_defaults(self, mock_init):
        """리스크분석가(DeepSeek) 실패 시 기본값 사용"""
        from scripts.run_macro_council import run_structured_council

        mock_strategist = MagicMock()
        # Step 1 성공, Step 2 실패 (동일 프로바이더이므로 side_effect로 순서 구분)
        mock_strategist.generate_json.side_effect = [
            SAMPLE_STRATEGIST_OUTPUT,                       # Step 1 성공
            Exception("DeepSeek 전체 체인 실패"),            # Step 2 실패
        ]

        mock_judge = MagicMock()
        mock_judge.generate_json_with_thinking.return_value = SAMPLE_JUDGE_OUTPUT

        mock_init.return_value = (mock_strategist, mock_strategist, mock_judge)

        result = run_structured_council("테스트 컨텍스트")

        assert "error" not in result
        # 리스크 기본값이 적용되어도 수석심판이 최종 결정
        assert result["sentiment"] == "neutral_to_bullish"

    @patch("scripts.run_macro_council._init_providers")
    def test_judge_failure_uses_fallback(self, mock_init):
        """수석심판(Claude) 실패 시 Step 1+2 직접 병합"""
        from scripts.run_macro_council import run_structured_council

        mock_strategist = MagicMock()
        mock_strategist.generate_json.side_effect = [
            SAMPLE_STRATEGIST_OUTPUT,  # Step 1
            SAMPLE_RISK_OUTPUT,        # Step 2
        ]

        mock_judge = MagicMock()
        mock_judge.generate_json_with_thinking.side_effect = Exception("Claude API 장애")

        mock_init.return_value = (mock_strategist, mock_strategist, mock_judge)

        result = run_structured_council("테스트 컨텍스트")

        assert "error" not in result
        # 폴백: 전략가 sentiment + 리스크분석가 조정 점수
        assert result["sentiment"] == "neutral_to_bullish"
        assert result["sentiment_score"] == 58  # 리스크분석가 조정
        assert result["council_consensus"] == "partial_disagree"

    @patch("scripts.run_macro_council._init_providers")
    def test_all_failures_returns_error(self, mock_init):
        """전략가+Fallback 모두 실패 시 에러 반환"""
        from scripts.run_macro_council import run_structured_council

        mock_strategist = MagicMock()
        mock_strategist.generate_json.side_effect = Exception("DeepSeek 실패")

        mock_judge = MagicMock()
        mock_judge.generate_json_with_thinking.side_effect = Exception("Claude도 실패")

        mock_init.return_value = (mock_strategist, mock_strategist, mock_judge)

        result = run_structured_council("테스트 컨텍스트")

        assert "error" in result


# ==============================================================================
# ClaudeLLMProvider.generate_json_with_thinking 테스트
# ==============================================================================

class TestClaudeThinking:
    """Extended Thinking 메서드 유닛 테스트"""

    @patch("shared.llm_providers.ClaudeLLMProvider.__init__", return_value=None)
    def test_parse_thinking_response(self, mock_init):
        """ThinkingBlock + TextBlock 응답 파싱"""
        from shared.llm_providers import ClaudeLLMProvider

        provider = ClaudeLLMProvider.__new__(ClaudeLLMProvider)
        provider.client = MagicMock()

        # Extended Thinking 응답 시뮬레이션
        thinking_block = MagicMock()
        thinking_block.type = "thinking"
        thinking_block.thinking = "Let me analyze the market..."

        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = json.dumps({"overall_sentiment": "bullish", "sentiment_score": 75})

        mock_response = MagicMock()
        mock_response.content = [thinking_block, text_block]
        mock_response.usage = MagicMock()
        mock_response.usage.input_tokens = 1000
        mock_response.usage.output_tokens = 500

        provider.client.messages.create.return_value = mock_response

        result = provider.generate_json_with_thinking(
            prompt="test prompt",
            response_schema={},
        )

        assert result["overall_sentiment"] == "bullish"
        assert result["sentiment_score"] == 75

    @patch("shared.llm_providers.ClaudeLLMProvider.__init__", return_value=None)
    def test_parse_json_in_code_block(self, mock_init):
        """```json 블록으로 감싼 응답 파싱"""
        from shared.llm_providers import ClaudeLLMProvider

        provider = ClaudeLLMProvider.__new__(ClaudeLLMProvider)
        provider.client = MagicMock()

        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = '```json\n{"score": 80}\n```'

        mock_response = MagicMock()
        mock_response.content = [text_block]
        mock_response.usage = MagicMock()
        mock_response.usage.input_tokens = 100
        mock_response.usage.output_tokens = 50

        provider.client.messages.create.return_value = mock_response

        result = provider.generate_json_with_thinking(
            prompt="test",
            response_schema={},
        )

        assert result["score"] == 80

    @patch("shared.llm_providers.ClaudeLLMProvider.__init__", return_value=None)
    def test_empty_text_raises(self, mock_init):
        """TextBlock이 없으면 ValueError"""
        from shared.llm_providers import ClaudeLLMProvider

        provider = ClaudeLLMProvider.__new__(ClaudeLLMProvider)
        provider.client = MagicMock()

        thinking_block = MagicMock()
        thinking_block.type = "thinking"

        mock_response = MagicMock()
        mock_response.content = [thinking_block]  # TextBlock 없음

        provider.client.messages.create.return_value = mock_response

        with pytest.raises(ValueError, match="TextBlock"):
            provider.generate_json_with_thinking(
                prompt="test",
                response_schema={},
            )
