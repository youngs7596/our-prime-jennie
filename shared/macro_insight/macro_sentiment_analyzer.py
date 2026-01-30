#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
shared/macro_insight/macro_sentiment_analyzer.py
-------------------------------------------------
LLM 기반 매크로 감성분석 모듈.

3현자 Council 권고사항 반영:
- 외부 정보 가중치 ≤10% (MAX_EXTERNAL_WEIGHT = 0.10)
- RISK_OFF 단독 발동 금지 (RISK_OFF_HINT만 제공)
- 편향 필터링 로직 포함
"""

import json
import logging
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ==============================================================================
# Constants (3현자 Council 권고)
# ==============================================================================

# 외부 정보 최대 가중치 (3현자 권고: ≤10%)
MAX_EXTERNAL_WEIGHT = 0.10

# 신호 발동 임계값
SIGNAL_THRESHOLD_RISK_ON = 0.3    # 긍정 신호 임계값
SIGNAL_THRESHOLD_RISK_OFF = -0.3  # 부정 신호 임계값 (HINT만 제공)

# 최소 신뢰도 (이 이하는 무시)
MIN_CONFIDENCE = 0.5

# 최소 기여 채널 수 (다중 검증)
MIN_CONTRIBUTING_CHANNELS = 2


class SignalType(Enum):
    """매크로 신호 유형 (3현자 권고 반영)"""
    RISK_ON = "RISK_ON"           # 적극 매수 신호
    NEUTRAL = "NEUTRAL"           # 중립
    RISK_OFF_HINT = "RISK_OFF_HINT"  # 주의 신호 (단독 발동 금지!)


class ChannelRole(Enum):
    """채널 역할"""
    MACRO_SIGNAL = "macro_signal"
    STOCK_REFERENCE = "stock_reference"


# ==============================================================================
# Data Classes
# ==============================================================================

@dataclass
class SentimentResult:
    """개별 메시지 감성분석 결과"""
    content_hash: str
    channel_username: str
    channel_role: str
    sentiment_score: float  # -1.0 (매우 부정) ~ +1.0 (매우 긍정)
    confidence: float       # 0.0 ~ 1.0
    macro_topics: List[str] = field(default_factory=list)
    key_phrases: List[str] = field(default_factory=list)
    analyzed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    raw_weight: float = 0.0  # 채널 가중치

    @property
    def weighted_score(self) -> float:
        """가중치 적용 점수"""
        return self.sentiment_score * self.raw_weight * self.confidence


@dataclass
class MacroSignal:
    """
    집계된 매크로 신호.

    3현자 Council 권고:
    - RISK_OFF 단독 발동 금지: should_influence_regime=False일 때 체크
    - 외부 정보 가중치 ≤10%: final_weight 필드로 제한
    """
    signal_type: SignalType
    weighted_score: float           # 가중 평균 점수
    contributing_channels: int      # 기여 채널 수
    total_messages: int             # 분석 메시지 수
    confidence: float               # 집계 신뢰도
    final_weight: float             # 최종 가중치 (≤0.10)
    should_influence_regime: bool   # MarketRegime 영향 여부
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리 변환 (JSON 직렬화용)"""
        result = asdict(self)
        result["signal_type"] = self.signal_type.value
        return result


# ==============================================================================
# Macro Keyword Extraction
# ==============================================================================

# 매크로 토픽별 키워드
MACRO_TOPIC_KEYWORDS = {
    "금리": ["금리", "기준금리", "FOMC", "Fed", "연준", "파월", "통화정책", "긴축", "완화"],
    "인플레이션": ["인플레이션", "물가", "CPI", "PCE", "디플레이션"],
    "환율": ["환율", "달러", "원달러", "엔화", "달러인덱스", "DXY"],
    "경기": ["경기", "GDP", "성장률", "침체", "리세션", "경착륙", "연착륙"],
    "무역": ["관세", "무역", "트럼프", "바이든", "미중", "수출", "수입"],
    "지정학": ["지정학", "전쟁", "우크라이나", "대만", "중동", "이란"],
    "유동성": ["유동성", "QE", "QT", "양적완화", "양적긴축", "자금"],
}

# 긍정/부정 키워드
POSITIVE_KEYWORDS = [
    "상승", "급등", "강세", "호조", "개선", "회복", "상향", "매수",
    "기대", "긍정", "완화", "부양", "호재", "돌파", "반등"
]

NEGATIVE_KEYWORDS = [
    "하락", "급락", "약세", "부진", "악화", "우려", "하향", "매도",
    "불안", "부정", "긴축", "리스크", "악재", "이탈", "붕괴", "침체"
]


def extract_macro_topics(content: str) -> List[str]:
    """콘텐츠에서 매크로 토픽 추출"""
    detected_topics = []
    for topic, keywords in MACRO_TOPIC_KEYWORDS.items():
        for kw in keywords:
            if kw in content:
                detected_topics.append(topic)
                break
    return list(set(detected_topics))


def extract_key_phrases(content: str) -> Tuple[List[str], List[str]]:
    """긍정/부정 핵심 문구 추출"""
    positive = [kw for kw in POSITIVE_KEYWORDS if kw in content]
    negative = [kw for kw in NEGATIVE_KEYWORDS if kw in content]
    return positive, negative


def compute_rule_based_sentiment(content: str) -> Tuple[float, float]:
    """
    규칙 기반 감성 점수 계산 (LLM fallback/검증용)

    Returns:
        (sentiment_score, confidence)
    """
    positive, negative = extract_key_phrases(content)
    pos_count = len(positive)
    neg_count = len(negative)
    total = pos_count + neg_count

    if total == 0:
        return 0.0, 0.3  # 중립, 낮은 신뢰도

    # 점수 계산
    score = (pos_count - neg_count) / total

    # 신뢰도: 키워드가 많을수록 높음
    confidence = min(0.9, 0.4 + (total * 0.1))

    return score, confidence


# ==============================================================================
# LLM-based Sentiment Analysis
# ==============================================================================

SENTIMENT_ANALYSIS_PROMPT = """당신은 한국 증권 시장 전문 매크로 분석가입니다.
다음 텔레그램 메시지를 분석하여 **시장 전체의 매크로 감성**을 JSON 형식으로 평가해주세요.

[분석 대상 메시지]
{content}

[분석 지침]
1. 이 메시지가 한국 주식시장 전체에 미치는 영향을 판단합니다.
2. 개별 종목이 아닌 **시장 전체(KOSPI, 코스닥)**에 대한 영향을 평가합니다.
3. 매크로 요인(금리, 환율, 경기, 무역, 지정학)을 중심으로 분석합니다.

[출력 형식 - JSON만 출력]
{{
    "sentiment_score": (숫자, -1.0 ~ +1.0, 음수=부정, 양수=긍정),
    "confidence": (숫자, 0.0 ~ 1.0, 분석 신뢰도),
    "macro_topics": ["토픽1", "토픽2"],
    "key_insight": "핵심 인사이트 한 줄",
    "reasoning": "판단 근거 요약"
}}
"""


def parse_llm_response(response: str) -> Optional[Dict[str, Any]]:
    """LLM 응답에서 JSON 추출"""
    try:
        # JSON 블록 찾기
        json_match = re.search(r'\{[^{}]*\}', response, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
    except json.JSONDecodeError:
        pass
    return None


class MacroSentimentAnalyzer:
    """
    LLM 기반 매크로 감성분석기.

    3현자 Council 권고:
    - 외부 정보 가중치 ≤10%
    - RISK_OFF 단독 발동 금지
    - 편향 필터링 및 다중 검증
    """

    def __init__(self, use_llm: bool = True):
        """
        Args:
            use_llm: LLM 사용 여부 (False면 규칙 기반만 사용)
        """
        self.use_llm = use_llm
        self._llm_provider = None

    def _get_llm_provider(self):
        """LLM Provider 지연 로딩"""
        if self._llm_provider is None and self.use_llm:
            try:
                from shared.llm_factory import LLMFactory, LLMTier
                self._llm_provider = LLMFactory.get_provider(LLMTier.FAST)
            except ImportError:
                logger.warning("LLM Factory 로드 실패, 규칙 기반 분석 사용")
                self.use_llm = False
        return self._llm_provider

    def analyze_content(
        self,
        content: str,
        channel_username: str,
        channel_role: str,
        content_hash: str,
        weight: float = 0.0
    ) -> SentimentResult:
        """
        단일 메시지 감성분석.

        Args:
            content: 메시지 내용
            channel_username: 채널 username
            channel_role: 채널 역할 (macro_signal, stock_reference)
            content_hash: 콘텐츠 해시
            weight: 채널 가중치

        Returns:
            SentimentResult
        """
        # 1. 매크로 토픽 추출
        macro_topics = extract_macro_topics(content)

        # 2. 긍정/부정 키워드 추출
        positive_phrases, negative_phrases = extract_key_phrases(content)
        key_phrases = positive_phrases + negative_phrases

        # 3. 감성 점수 계산
        if self.use_llm:
            sentiment_score, confidence = self._analyze_with_llm(content)

            # LLM 실패 시 규칙 기반 fallback
            if sentiment_score is None:
                sentiment_score, confidence = compute_rule_based_sentiment(content)
        else:
            sentiment_score, confidence = compute_rule_based_sentiment(content)

        # 4. 편향 필터링: stock_reference 채널의 종목 분석은 가중치 감소
        if channel_role == ChannelRole.STOCK_REFERENCE.value:
            # 종목 코드가 포함된 콘텐츠는 매크로 영향력 감소
            if re.search(r'\d{6}\.KS', content):
                weight *= 0.5
                confidence *= 0.7

        return SentimentResult(
            content_hash=content_hash,
            channel_username=channel_username,
            channel_role=channel_role,
            sentiment_score=sentiment_score,
            confidence=confidence,
            macro_topics=macro_topics,
            key_phrases=key_phrases,
            raw_weight=weight,
        )

    def _analyze_with_llm(self, content: str) -> Tuple[Optional[float], float]:
        """
        LLM을 사용한 감성분석.

        Returns:
            (sentiment_score, confidence) 또는 (None, 0.0) if 실패
        """
        provider = self._get_llm_provider()
        if not provider:
            return None, 0.0

        try:
            prompt = SENTIMENT_ANALYSIS_PROMPT.format(content=content[:2000])
            response = provider.generate(prompt, max_tokens=500)

            parsed = parse_llm_response(response)
            if parsed:
                score = float(parsed.get("sentiment_score", 0))
                conf = float(parsed.get("confidence", 0.5))

                # 범위 클램핑
                score = max(-1.0, min(1.0, score))
                conf = max(0.0, min(1.0, conf))

                return score, conf
        except Exception as e:
            logger.error(f"LLM 감성분석 오류: {e}")

        return None, 0.0

    def analyze_batch(
        self,
        messages: List[Dict[str, Any]]
    ) -> List[SentimentResult]:
        """
        배치 메시지 감성분석.

        Args:
            messages: [{"page_content": str, "metadata": dict}, ...]

        Returns:
            List[SentimentResult]
        """
        results = []

        for msg in messages:
            try:
                content = msg.get("page_content", "")
                metadata = msg.get("metadata", {})

                result = self.analyze_content(
                    content=content,
                    channel_username=metadata.get("channel_username", "unknown"),
                    channel_role=metadata.get("channel_role", "unknown"),
                    content_hash=metadata.get("content_hash", ""),
                    weight=metadata.get("weight", 0.0),
                )
                results.append(result)
            except Exception as e:
                logger.error(f"메시지 분석 오류: {e}")

        return results

    def get_aggregated_signal(
        self,
        results: List[SentimentResult]
    ) -> MacroSignal:
        """
        감성분석 결과를 집계하여 최종 매크로 신호 생성.

        3현자 Council 권고 적용:
        - 외부 정보 가중치 ≤10%
        - RISK_OFF 단독 발동 금지
        - 최소 2개 이상 채널의 다중 검증

        Args:
            results: 감성분석 결과 리스트

        Returns:
            MacroSignal
        """
        if not results:
            return MacroSignal(
                signal_type=SignalType.NEUTRAL,
                weighted_score=0.0,
                contributing_channels=0,
                total_messages=0,
                confidence=0.0,
                final_weight=0.0,
                should_influence_regime=False,
                details={"reason": "no_data"},
            )

        # 1. 최소 신뢰도 필터링
        valid_results = [r for r in results if r.confidence >= MIN_CONFIDENCE]

        if not valid_results:
            return MacroSignal(
                signal_type=SignalType.NEUTRAL,
                weighted_score=0.0,
                contributing_channels=0,
                total_messages=len(results),
                confidence=0.0,
                final_weight=0.0,
                should_influence_regime=False,
                details={"reason": "low_confidence"},
            )

        # 2. 가중 평균 점수 계산
        total_weight = sum(r.raw_weight * r.confidence for r in valid_results)
        if total_weight == 0:
            weighted_score = sum(r.sentiment_score for r in valid_results) / len(valid_results)
        else:
            weighted_score = sum(r.weighted_score for r in valid_results) / total_weight

        # 3. 기여 채널 수 계산
        contributing_channels = len(set(r.channel_username for r in valid_results))

        # 4. 집계 신뢰도
        avg_confidence = sum(r.confidence for r in valid_results) / len(valid_results)

        # 5. 신호 유형 결정
        if weighted_score >= SIGNAL_THRESHOLD_RISK_ON:
            signal_type = SignalType.RISK_ON
        elif weighted_score <= SIGNAL_THRESHOLD_RISK_OFF:
            signal_type = SignalType.RISK_OFF_HINT  # 단독 발동 금지!
        else:
            signal_type = SignalType.NEUTRAL

        # 6. MarketRegime 영향 여부 결정 (3현자 권고)
        should_influence = True
        influence_reason = "normal"

        # 조건 1: 최소 기여 채널 수 미달
        if contributing_channels < MIN_CONTRIBUTING_CHANNELS:
            should_influence = False
            influence_reason = f"insufficient_channels ({contributing_channels} < {MIN_CONTRIBUTING_CHANNELS})"

        # 조건 2: RISK_OFF_HINT는 절대 단독 영향 불가 (3현자 핵심 권고)
        if signal_type == SignalType.RISK_OFF_HINT:
            should_influence = False
            influence_reason = "risk_off_hint_cannot_influence_alone"

        # 조건 3: 신뢰도 부족
        if avg_confidence < 0.6:
            should_influence = False
            influence_reason = f"low_aggregated_confidence ({avg_confidence:.2f})"

        # 7. 최종 가중치 계산 (3현자 권고: ≤10%)
        raw_final_weight = min(MAX_EXTERNAL_WEIGHT, avg_confidence * 0.15)
        final_weight = raw_final_weight if should_influence else 0.0

        # 8. 상세 정보
        details = {
            "influence_reason": influence_reason,
            "macro_topics": list(set(
                topic for r in valid_results for topic in r.macro_topics
            )),
            "channel_breakdown": {
                r.channel_username: r.sentiment_score
                for r in valid_results
            },
            "positive_signals": sum(1 for r in valid_results if r.sentiment_score > 0),
            "negative_signals": sum(1 for r in valid_results if r.sentiment_score < 0),
        }

        logger.info(
            f"[MacroSignal] {signal_type.value}: "
            f"score={weighted_score:.3f}, "
            f"channels={contributing_channels}, "
            f"influence={should_influence} ({influence_reason})"
        )

        return MacroSignal(
            signal_type=signal_type,
            weighted_score=weighted_score,
            contributing_channels=contributing_channels,
            total_messages=len(results),
            confidence=avg_confidence,
            final_weight=final_weight,
            should_influence_regime=should_influence,
            details=details,
        )


# ==============================================================================
# Convenience Functions
# ==============================================================================

def analyze_macro_messages(
    messages: List[Dict[str, Any]],
    use_llm: bool = True
) -> MacroSignal:
    """
    매크로 메시지를 분석하여 집계 신호 반환.

    Args:
        messages: TelegramCollector에서 수집한 메시지 리스트
        use_llm: LLM 사용 여부

    Returns:
        MacroSignal
    """
    analyzer = MacroSentimentAnalyzer(use_llm=use_llm)
    results = analyzer.analyze_batch(messages)
    return analyzer.get_aggregated_signal(results)
