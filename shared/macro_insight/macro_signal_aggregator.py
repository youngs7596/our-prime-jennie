#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
shared/macro_insight/macro_signal_aggregator.py
-----------------------------------------------
매크로 신호를 집계하여 MarketRegimeDetector에 보조 입력으로 제공.

3현자 Council 권고:
- 외부 정보 가중치 ≤10%
- RISK_OFF 단독 발동 금지
- MarketRegimeDetector의 보조 입력으로만 사용
"""

import logging
import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
import threading

from shared.macro_insight.macro_sentiment_analyzer import (
    MacroSentimentAnalyzer,
    MacroSignal,
    SignalType,
    SentimentResult,
    MAX_EXTERNAL_WEIGHT,
)

logger = logging.getLogger(__name__)


# ==============================================================================
# Configuration
# ==============================================================================

# 신호 캐시 TTL (분)
SIGNAL_CACHE_TTL_MINUTES = 30

# 최대 캐시 메시지 수
MAX_CACHED_MESSAGES = 100


# ==============================================================================
# MacroSignal Cache (Thread-Safe)
# ==============================================================================

@dataclass
class CachedMacroSignal:
    """캐시된 매크로 신호"""
    signal: MacroSignal
    created_at: datetime
    source_messages: int

    def is_valid(self, ttl_minutes: int = SIGNAL_CACHE_TTL_MINUTES) -> bool:
        """TTL 내 유효 여부"""
        age = datetime.now(timezone.utc) - self.created_at
        return age < timedelta(minutes=ttl_minutes)


class MacroSignalCache:
    """스레드 안전한 매크로 신호 캐시"""

    def __init__(self):
        self._lock = threading.Lock()
        self._current_signal: Optional[CachedMacroSignal] = None
        self._messages: List[Dict[str, Any]] = []

    def add_message(self, message: Dict[str, Any]):
        """새 메시지 추가"""
        with self._lock:
            self._messages.append(message)
            # 최대 캐시 크기 유지
            if len(self._messages) > MAX_CACHED_MESSAGES:
                self._messages = self._messages[-MAX_CACHED_MESSAGES:]
            # 신호 무효화 (재계산 필요)
            self._current_signal = None

    def get_messages(self) -> List[Dict[str, Any]]:
        """캐시된 메시지 조회"""
        with self._lock:
            return list(self._messages)

    def set_signal(self, signal: MacroSignal, source_count: int):
        """신호 캐시"""
        with self._lock:
            self._current_signal = CachedMacroSignal(
                signal=signal,
                created_at=datetime.now(timezone.utc),
                source_messages=source_count,
            )

    def get_signal(self) -> Optional[MacroSignal]:
        """캐시된 신호 조회 (TTL 유효 시)"""
        with self._lock:
            if self._current_signal and self._current_signal.is_valid():
                return self._current_signal.signal
            return None

    def clear(self):
        """캐시 초기화"""
        with self._lock:
            self._messages.clear()
            self._current_signal = None


# 전역 캐시 인스턴스
_signal_cache = MacroSignalCache()


# ==============================================================================
# MacroSignalAggregator
# ==============================================================================

class MacroSignalAggregator:
    """
    매크로 신호 집계기.

    TelegramCollector에서 수집한 메시지를 분석하여
    MarketRegimeDetector의 보조 입력으로 제공합니다.

    3현자 Council 권고:
    - 외부 정보 가중치 ≤10%
    - RISK_OFF 단독 발동 금지
    - 정량 분석(price-based)이 주, 매크로 인사이트는 보조
    """

    def __init__(self, use_llm: bool = True):
        """
        Args:
            use_llm: LLM 사용 여부 (False면 규칙 기반만 사용)
        """
        self.analyzer = MacroSentimentAnalyzer(use_llm=use_llm)
        self.cache = _signal_cache

    def process_message(self, message: Dict[str, Any]) -> bool:
        """
        단일 메시지 처리.

        Args:
            message: {"page_content": str, "metadata": dict}

        Returns:
            처리 성공 여부
        """
        try:
            self.cache.add_message(message)
            logger.debug(f"[MacroAggregator] 메시지 추가: {message.get('metadata', {}).get('channel_username', 'unknown')}")
            return True
        except Exception as e:
            logger.error(f"[MacroAggregator] 메시지 처리 오류: {e}")
            return False

    def get_current_signal(self, force_refresh: bool = False) -> MacroSignal:
        """
        현재 매크로 신호 조회.

        Args:
            force_refresh: 캐시 무시하고 재계산

        Returns:
            MacroSignal
        """
        # 캐시 확인
        if not force_refresh:
            cached = self.cache.get_signal()
            if cached:
                return cached

        # 새로 계산
        messages = self.cache.get_messages()
        if not messages:
            return MacroSignal(
                signal_type=SignalType.NEUTRAL,
                weighted_score=0.0,
                contributing_channels=0,
                total_messages=0,
                confidence=0.0,
                final_weight=0.0,
                should_influence_regime=False,
                details={"reason": "no_cached_messages"},
            )

        # 분석 및 집계
        results = self.analyzer.analyze_batch(messages)
        signal = self.analyzer.get_aggregated_signal(results)

        # 캐시 저장
        self.cache.set_signal(signal, len(messages))

        return signal

    def get_regime_adjustment(self) -> Dict[str, Any]:
        """
        MarketRegimeDetector 조정 정보 반환.

        3현자 Council 권고:
        - RISK_OFF 단독 발동 금지: adjust_regime=False
        - 외부 정보 가중치 ≤10%: weight 필드로 제한

        Returns:
            {
                "should_adjust": bool,
                "adjustment_weight": float (≤0.10),
                "suggested_direction": str ("bullish", "neutral", "bearish_hint"),
                "signal_details": MacroSignal.to_dict()
            }
        """
        signal = self.get_current_signal()

        # 기본: 조정 안함
        adjustment = {
            "should_adjust": False,
            "adjustment_weight": 0.0,
            "suggested_direction": "neutral",
            "signal_details": signal.to_dict(),
        }

        # 영향력 있는 신호만 조정
        if not signal.should_influence_regime:
            adjustment["reason"] = signal.details.get("influence_reason", "unknown")
            return adjustment

        # 신호 유형별 방향 설정
        if signal.signal_type == SignalType.RISK_ON:
            adjustment["should_adjust"] = True
            adjustment["adjustment_weight"] = signal.final_weight
            adjustment["suggested_direction"] = "bullish"
        elif signal.signal_type == SignalType.RISK_OFF_HINT:
            # RISK_OFF_HINT는 힌트만 제공 (단독 발동 금지)
            adjustment["should_adjust"] = False  # 강제 False
            adjustment["suggested_direction"] = "bearish_hint"
            adjustment["reason"] = "risk_off_hint_cannot_trigger_alone"
        else:
            adjustment["suggested_direction"] = "neutral"

        return adjustment

    def clear_cache(self):
        """캐시 초기화"""
        self.cache.clear()
        logger.info("[MacroAggregator] 캐시 초기화 완료")


# ==============================================================================
# Convenience Functions
# ==============================================================================

def get_macro_regime_adjustment(use_llm: bool = True) -> Dict[str, Any]:
    """
    현재 매크로 신호 기반 Regime 조정 정보 반환.

    Args:
        use_llm: LLM 사용 여부

    Returns:
        MarketRegimeDetector 조정 정보
    """
    aggregator = MacroSignalAggregator(use_llm=use_llm)
    return aggregator.get_regime_adjustment()


def process_telegram_message(message: Dict[str, Any]) -> bool:
    """
    TelegramCollector 메시지 처리.

    Args:
        message: {"page_content": str, "metadata": dict}

    Returns:
        처리 성공 여부
    """
    aggregator = MacroSignalAggregator()
    return aggregator.process_message(message)


# ==============================================================================
# MarketRegimeDetector Integration Helper
# ==============================================================================

def apply_macro_adjustment_to_regime(
    base_regime: str,
    regime_context: Dict[str, Any],
    macro_adjustment: Dict[str, Any]
) -> tuple[str, Dict[str, Any]]:
    """
    매크로 신호를 기존 Regime 판단에 반영.

    3현자 Council 권고:
    - 외부 정보는 보조 역할에 머물러야 함
    - Regime 자체를 변경하지 않고, context에 정보 추가
    - RISK_OFF 단독 발동 금지: bearish_hint는 경고만 제공

    Args:
        base_regime: 가격 기반 Regime (STRONG_BULL, BULL, SIDEWAYS, BEAR)
        regime_context: Regime 판단 컨텍스트
        macro_adjustment: get_regime_adjustment() 결과

    Returns:
        (adjusted_regime, enriched_context)
    """
    # 기본: Regime 변경 없음
    adjusted_regime = base_regime
    enriched_context = dict(regime_context)

    # 매크로 정보 추가
    enriched_context["macro_signal"] = macro_adjustment.get("signal_details", {})
    enriched_context["macro_influence"] = {
        "should_adjust": macro_adjustment.get("should_adjust", False),
        "weight": macro_adjustment.get("adjustment_weight", 0.0),
        "direction": macro_adjustment.get("suggested_direction", "neutral"),
    }

    # 조정 적용 (보조 역할로만)
    if not macro_adjustment.get("should_adjust", False):
        enriched_context["macro_influence"]["reason"] = macro_adjustment.get("reason", "no_adjustment")
        return adjusted_regime, enriched_context

    direction = macro_adjustment.get("suggested_direction", "neutral")
    weight = macro_adjustment.get("adjustment_weight", 0.0)

    # Regime 점수 조정 (기존 점수에 가중치 적용)
    if "regime_scores" in enriched_context:
        scores = enriched_context["regime_scores"]

        if direction == "bullish":
            # RISK_ON: BULL/STRONG_BULL 점수 소폭 상향
            if "BULL" in scores:
                scores["BULL"] = scores["BULL"] * (1 + weight)
            if "STRONG_BULL" in scores:
                scores["STRONG_BULL"] = scores["STRONG_BULL"] * (1 + weight)
            enriched_context["macro_influence"]["applied"] = True
            logger.info(f"[MacroIntegration] RISK_ON 신호 반영: BULL 점수 +{weight*100:.1f}%")

        # bearish_hint는 경고만 (점수 조정 안함 - 3현자 권고)
        elif direction == "bearish_hint":
            enriched_context["macro_influence"]["warning"] = "매크로 부정 신호 감지. 주의 필요."
            enriched_context["macro_influence"]["applied"] = False
            logger.warning("[MacroIntegration] RISK_OFF_HINT 감지: 경고만 제공 (단독 발동 금지)")

    return adjusted_regime, enriched_context
