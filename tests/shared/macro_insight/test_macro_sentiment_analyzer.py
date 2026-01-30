#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/shared/macro_insight/test_macro_sentiment_analyzer.py
-----------------------------------------------------------
MacroSentimentAnalyzer 단위 테스트

3현자 Council 권고사항 검증:
- 외부 정보 가중치 ≤10%
- RISK_OFF 단독 발동 금지
- 편향 필터링 및 다중 검증
"""

import os
import sys
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, patch, MagicMock

# 프로젝트 루트 설정
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, PROJECT_ROOT)

from shared.macro_insight.macro_sentiment_analyzer import (
    MacroSentimentAnalyzer,
    SentimentResult,
    MacroSignal,
    SignalType,
    extract_macro_topics,
    extract_key_phrases,
    compute_rule_based_sentiment,
    parse_llm_response,
    MAX_EXTERNAL_WEIGHT,
    MIN_CONFIDENCE,
    MIN_CONTRIBUTING_CHANNELS,
    SIGNAL_THRESHOLD_RISK_ON,
    SIGNAL_THRESHOLD_RISK_OFF,
)


class TestConstants:
    """상수 테스트 (3현자 권고 검증)"""

    def test_max_external_weight(self):
        """외부 정보 가중치 ≤10% 확인"""
        assert MAX_EXTERNAL_WEIGHT <= 0.10

    def test_min_contributing_channels(self):
        """다중 검증을 위한 최소 채널 수"""
        assert MIN_CONTRIBUTING_CHANNELS >= 2

    def test_signal_thresholds(self):
        """신호 임계값 대칭성"""
        assert SIGNAL_THRESHOLD_RISK_ON == -SIGNAL_THRESHOLD_RISK_OFF


class TestMacroTopicExtraction:
    """매크로 토픽 추출 테스트"""

    def test_extract_interest_rate_topic(self):
        """금리 관련 토픽 추출"""
        content = "FOMC 금리 인상 결정. 연준 파월 의장 발언 주목."
        topics = extract_macro_topics(content)
        assert "금리" in topics

    def test_extract_currency_topic(self):
        """환율 관련 토픽 추출"""
        content = "원달러 환율 1,450원 돌파. 달러 강세 지속."
        topics = extract_macro_topics(content)
        assert "환율" in topics

    def test_extract_trade_topic(self):
        """무역 관련 토픽 추출"""
        content = "트럼프 대통령 관세 부과 시사. 미중 무역 갈등 재점화."
        topics = extract_macro_topics(content)
        assert "무역" in topics

    def test_extract_economy_topic(self):
        """경기 관련 토픽 추출"""
        content = "GDP 성장률 둔화. 경기 침체 우려 확산."
        topics = extract_macro_topics(content)
        assert "경기" in topics

    def test_extract_multiple_topics(self):
        """다중 토픽 추출"""
        content = "FOMC 금리 인상으로 원달러 환율 상승. GDP 둔화 전망."
        topics = extract_macro_topics(content)
        assert len(topics) >= 2
        assert "금리" in topics
        assert "환율" in topics

    def test_extract_no_topic(self):
        """매크로 토픽 없는 콘텐츠"""
        content = "삼성전자 4분기 실적 호조. 목표주가 상향."
        topics = extract_macro_topics(content)
        # 경기와 관련된 키워드가 없으면 빈 리스트
        assert "금리" not in topics
        assert "환율" not in topics


class TestKeyPhraseExtraction:
    """핵심 문구 추출 테스트"""

    def test_extract_positive_phrases(self):
        """긍정 문구 추출"""
        content = "반도체 업종 강세. 기대감 상승. 반등 기대."
        positive, negative = extract_key_phrases(content)
        assert "강세" in positive
        assert "상승" in positive
        assert "반등" in positive

    def test_extract_negative_phrases(self):
        """부정 문구 추출"""
        content = "시장 약세 지속. 리스크 확대. 하락 우려."
        positive, negative = extract_key_phrases(content)
        assert "약세" in negative
        assert "리스크" in negative
        assert "하락" in negative
        assert "우려" in negative

    def test_extract_mixed_phrases(self):
        """긍정/부정 혼재 문구"""
        content = "반도체 강세 vs 금융 약세. 상승과 하락 혼조."
        positive, negative = extract_key_phrases(content)
        assert len(positive) > 0
        assert len(negative) > 0


class TestRuleBasedSentiment:
    """규칙 기반 감성분석 테스트"""

    def test_positive_sentiment(self):
        """긍정 감성"""
        content = "강세 상승 호조 개선 기대"
        score, confidence = compute_rule_based_sentiment(content)
        assert score > 0
        assert confidence > 0

    def test_negative_sentiment(self):
        """부정 감성"""
        content = "약세 하락 부진 악화 우려"
        score, confidence = compute_rule_based_sentiment(content)
        assert score < 0
        assert confidence > 0

    def test_neutral_sentiment(self):
        """중립 감성 (키워드 균형)"""
        content = "강세와 약세가 혼재. 상승과 하락 반복."
        score, confidence = compute_rule_based_sentiment(content)
        assert -0.5 <= score <= 0.5

    def test_no_keyword_sentiment(self):
        """키워드 없는 경우"""
        content = "오늘 날씨가 좋습니다."
        score, confidence = compute_rule_based_sentiment(content)
        assert score == 0.0
        assert confidence < 0.5


class TestLLMResponseParsing:
    """LLM 응답 파싱 테스트"""

    def test_parse_valid_json(self):
        """정상 JSON 파싱"""
        response = '{"sentiment_score": 0.5, "confidence": 0.8}'
        parsed = parse_llm_response(response)
        assert parsed is not None
        assert parsed["sentiment_score"] == 0.5
        assert parsed["confidence"] == 0.8

    def test_parse_json_with_text(self):
        """텍스트 포함 JSON 파싱"""
        response = """분석 결과입니다.
        {"sentiment_score": -0.3, "confidence": 0.7, "key_insight": "시장 부정적"}
        위 결과를 참고하세요."""
        parsed = parse_llm_response(response)
        assert parsed is not None
        assert parsed["sentiment_score"] == -0.3

    def test_parse_invalid_json(self):
        """잘못된 JSON 처리"""
        response = "이것은 JSON이 아닙니다"
        parsed = parse_llm_response(response)
        assert parsed is None


class TestSentimentResult:
    """SentimentResult 데이터 클래스 테스트"""

    def test_weighted_score_calculation(self):
        """가중 점수 계산"""
        result = SentimentResult(
            content_hash="abc123",
            channel_username="hedgecat0301",
            channel_role="macro_signal",
            sentiment_score=0.5,
            confidence=0.8,
            macro_topics=["금리"],
            raw_weight=0.6,
        )
        # weighted_score = sentiment_score * raw_weight * confidence
        expected = 0.5 * 0.6 * 0.8
        assert result.weighted_score == expected

    def test_zero_weight(self):
        """가중치 0인 경우"""
        result = SentimentResult(
            content_hash="abc123",
            channel_username="test",
            channel_role="stock_reference",
            sentiment_score=0.5,
            confidence=0.8,
            raw_weight=0.0,
        )
        assert result.weighted_score == 0.0


class TestMacroSentimentAnalyzer:
    """MacroSentimentAnalyzer 클래스 테스트"""

    def test_analyze_content_rule_based(self):
        """규칙 기반 분석"""
        analyzer = MacroSentimentAnalyzer(use_llm=False)
        result = analyzer.analyze_content(
            content="시장 강세 지속. 반도체 업종 상승 기대.",
            channel_username="hedgecat0301",
            channel_role="macro_signal",
            content_hash="test123",
            weight=0.6,
        )
        assert isinstance(result, SentimentResult)
        assert result.sentiment_score > 0  # 긍정
        assert result.channel_username == "hedgecat0301"
        assert result.raw_weight == 0.6

    def test_analyze_content_with_stock_code_penalty(self):
        """종목코드 포함 시 가중치 감소 (편향 필터링)"""
        analyzer = MacroSentimentAnalyzer(use_llm=False)

        # 종목코드 포함
        result_with_code = analyzer.analyze_content(
            content="삼성전자 (005930.KS) 강세. 매수 추천.",
            channel_username="HanaResearch",
            channel_role="stock_reference",
            content_hash="test456",
            weight=0.2,
        )

        # 종목코드 미포함
        result_without_code = analyzer.analyze_content(
            content="시장 전체 강세. 매수 추천.",
            channel_username="HanaResearch",
            channel_role="stock_reference",
            content_hash="test789",
            weight=0.2,
        )

        # 종목코드 포함 시 가중치 감소
        assert result_with_code.raw_weight < result_without_code.raw_weight

    def test_analyze_batch(self):
        """배치 분석"""
        analyzer = MacroSentimentAnalyzer(use_llm=False)

        messages = [
            {
                "page_content": "FOMC 금리 인상. 시장 약세 우려.",
                "metadata": {
                    "channel_username": "hedgecat0301",
                    "channel_role": "macro_signal",
                    "content_hash": "msg1",
                    "weight": 0.6,
                }
            },
            {
                "page_content": "반도체 강세. 업황 개선 기대.",
                "metadata": {
                    "channel_username": "HanaResearch",
                    "channel_role": "stock_reference",
                    "content_hash": "msg2",
                    "weight": 0.2,
                }
            },
        ]

        results = analyzer.analyze_batch(messages)
        assert len(results) == 2
        assert all(isinstance(r, SentimentResult) for r in results)


class TestMacroSignalAggregation:
    """MacroSignal 집계 테스트 (3현자 권고 검증)"""

    def setup_method(self):
        """테스트 설정"""
        self.analyzer = MacroSentimentAnalyzer(use_llm=False)

    def test_empty_results(self):
        """빈 결과 처리"""
        signal = self.analyzer.get_aggregated_signal([])
        assert signal.signal_type == SignalType.NEUTRAL
        assert signal.should_influence_regime is False
        assert signal.final_weight == 0.0

    def test_low_confidence_filter(self):
        """낮은 신뢰도 필터링"""
        results = [
            SentimentResult(
                content_hash="1",
                channel_username="ch1",
                channel_role="macro_signal",
                sentiment_score=0.8,
                confidence=0.3,  # MIN_CONFIDENCE 미달
                raw_weight=0.6,
            ),
        ]
        signal = self.analyzer.get_aggregated_signal(results)
        assert signal.should_influence_regime is False
        assert signal.details["reason"] == "low_confidence"

    def test_insufficient_channels(self):
        """최소 채널 수 미달 (다중 검증 실패)"""
        results = [
            SentimentResult(
                content_hash="1",
                channel_username="ch1",  # 단일 채널
                channel_role="macro_signal",
                sentiment_score=0.8,
                confidence=0.9,
                raw_weight=0.6,
            ),
        ]
        signal = self.analyzer.get_aggregated_signal(results)
        assert signal.contributing_channels < MIN_CONTRIBUTING_CHANNELS
        assert signal.should_influence_regime is False
        assert "insufficient_channels" in signal.details["influence_reason"]

    def test_risk_off_hint_cannot_influence_alone(self):
        """RISK_OFF_HINT 단독 발동 금지 (3현자 핵심 권고)"""
        results = [
            SentimentResult(
                content_hash="1",
                channel_username="ch1",
                channel_role="macro_signal",
                sentiment_score=-0.8,  # 강한 부정
                confidence=0.9,
                raw_weight=0.6,
            ),
            SentimentResult(
                content_hash="2",
                channel_username="ch2",
                channel_role="macro_signal",
                sentiment_score=-0.7,  # 강한 부정
                confidence=0.9,
                raw_weight=0.4,
            ),
        ]
        signal = self.analyzer.get_aggregated_signal(results)

        # RISK_OFF_HINT로 분류
        assert signal.signal_type == SignalType.RISK_OFF_HINT

        # 단독 영향 불가 (3현자 핵심 권고)
        assert signal.should_influence_regime is False
        assert "risk_off_hint_cannot_influence_alone" in signal.details["influence_reason"]

    def test_risk_on_can_influence(self):
        """RISK_ON은 조건 충족 시 영향 가능"""
        results = [
            SentimentResult(
                content_hash="1",
                channel_username="ch1",
                channel_role="macro_signal",
                sentiment_score=0.6,
                confidence=0.9,
                raw_weight=0.6,
            ),
            SentimentResult(
                content_hash="2",
                channel_username="ch2",
                channel_role="macro_signal",
                sentiment_score=0.5,
                confidence=0.8,
                raw_weight=0.4,
            ),
        ]
        signal = self.analyzer.get_aggregated_signal(results)

        assert signal.signal_type == SignalType.RISK_ON
        assert signal.contributing_channels >= MIN_CONTRIBUTING_CHANNELS
        assert signal.should_influence_regime is True

    def test_max_external_weight_limit(self):
        """외부 정보 가중치 ≤10% 제한 (3현자 권고)"""
        results = [
            SentimentResult(
                content_hash="1",
                channel_username="ch1",
                channel_role="macro_signal",
                sentiment_score=0.9,
                confidence=0.99,  # 매우 높은 신뢰도
                raw_weight=0.6,
            ),
            SentimentResult(
                content_hash="2",
                channel_username="ch2",
                channel_role="macro_signal",
                sentiment_score=0.8,
                confidence=0.99,
                raw_weight=0.4,
            ),
        ]
        signal = self.analyzer.get_aggregated_signal(results)

        # final_weight는 MAX_EXTERNAL_WEIGHT를 초과할 수 없음
        assert signal.final_weight <= MAX_EXTERNAL_WEIGHT

    def test_signal_type_neutral(self):
        """중립 신호 분류"""
        results = [
            SentimentResult(
                content_hash="1",
                channel_username="ch1",
                channel_role="macro_signal",
                sentiment_score=0.1,  # 약한 긍정
                confidence=0.8,
                raw_weight=0.6,
            ),
            SentimentResult(
                content_hash="2",
                channel_username="ch2",
                channel_role="macro_signal",
                sentiment_score=-0.1,  # 약한 부정
                confidence=0.8,
                raw_weight=0.4,
            ),
        ]
        signal = self.analyzer.get_aggregated_signal(results)
        assert signal.signal_type == SignalType.NEUTRAL


class TestMacroSignalDataClass:
    """MacroSignal 데이터 클래스 테스트"""

    def test_to_dict(self):
        """딕셔너리 변환"""
        signal = MacroSignal(
            signal_type=SignalType.RISK_ON,
            weighted_score=0.5,
            contributing_channels=3,
            total_messages=5,
            confidence=0.8,
            final_weight=0.08,
            should_influence_regime=True,
            details={"key": "value"},
        )
        result = signal.to_dict()

        assert result["signal_type"] == "RISK_ON"
        assert result["weighted_score"] == 0.5
        assert result["final_weight"] == 0.08
        assert result["should_influence_regime"] is True


class TestEdgeCases:
    """엣지 케이스 테스트"""

    def test_empty_content(self):
        """빈 콘텐츠"""
        analyzer = MacroSentimentAnalyzer(use_llm=False)
        result = analyzer.analyze_content(
            content="",
            channel_username="test",
            channel_role="macro_signal",
            content_hash="empty",
            weight=0.5,
        )
        assert result.sentiment_score == 0.0

    def test_very_long_content(self):
        """매우 긴 콘텐츠"""
        analyzer = MacroSentimentAnalyzer(use_llm=False)
        long_content = "시장 강세. " * 1000  # 긴 텍스트
        result = analyzer.analyze_content(
            content=long_content,
            channel_username="test",
            channel_role="macro_signal",
            content_hash="long",
            weight=0.5,
        )
        assert result is not None
        assert result.sentiment_score > 0

    def test_unicode_content(self):
        """유니코드 콘텐츠"""
        analyzer = MacroSentimentAnalyzer(use_llm=False)
        result = analyzer.analyze_content(
            content="한글 테스트 강세 상승 환율",
            channel_username="test",
            channel_role="macro_signal",
            content_hash="unicode",
            weight=0.5,
        )
        assert "환율" in result.macro_topics


# ==============================================================================
# Integration Tests (with Mock LLM)
# ==============================================================================

class TestLLMIntegration:
    """LLM 연동 테스트 (Mock)"""

    @patch('shared.macro_insight.macro_sentiment_analyzer.MacroSentimentAnalyzer._get_llm_provider')
    def test_llm_analysis_success(self, mock_get_provider):
        """LLM 분석 성공"""
        mock_provider = MagicMock()
        mock_provider.generate.return_value = '{"sentiment_score": 0.6, "confidence": 0.85}'
        mock_get_provider.return_value = mock_provider

        analyzer = MacroSentimentAnalyzer(use_llm=True)
        score, confidence = analyzer._analyze_with_llm("테스트 콘텐츠")

        assert score == 0.6
        assert confidence == 0.85

    @patch('shared.macro_insight.macro_sentiment_analyzer.MacroSentimentAnalyzer._get_llm_provider')
    def test_llm_analysis_fallback(self, mock_get_provider):
        """LLM 실패 시 규칙 기반 fallback"""
        mock_provider = MagicMock()
        mock_provider.generate.side_effect = Exception("LLM Error")
        mock_get_provider.return_value = mock_provider

        analyzer = MacroSentimentAnalyzer(use_llm=True)
        score, confidence = analyzer._analyze_with_llm("테스트 콘텐츠")

        # LLM 실패 시 None 반환
        assert score is None
        assert confidence == 0.0

    @patch('shared.macro_insight.macro_sentiment_analyzer.MacroSentimentAnalyzer._get_llm_provider')
    def test_llm_score_clamping(self, mock_get_provider):
        """LLM 점수 범위 클램핑"""
        mock_provider = MagicMock()
        # 범위 초과 값 반환
        mock_provider.generate.return_value = '{"sentiment_score": 1.5, "confidence": 1.2}'
        mock_get_provider.return_value = mock_provider

        analyzer = MacroSentimentAnalyzer(use_llm=True)
        score, confidence = analyzer._analyze_with_llm("테스트")

        # -1.0 ~ 1.0 범위로 클램핑
        assert -1.0 <= score <= 1.0
        assert 0.0 <= confidence <= 1.0


# ==============================================================================
# Test Runner
# ==============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
