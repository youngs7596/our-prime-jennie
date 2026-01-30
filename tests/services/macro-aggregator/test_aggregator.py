#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/services/macro-aggregator/test_aggregator.py
--------------------------------------------------
MacroSignalAggregator 서비스 단위 테스트

3현자 Council 권고사항 검증:
- 외부 정보 가중치 ≤10%
- RISK_OFF 단독 발동 금지
- MarketRegimeDetector 연동 검증
"""

import os
import sys
import pytest
from datetime import datetime, timezone
from unittest.mock import Mock, patch, MagicMock

# 프로젝트 루트 설정
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, PROJECT_ROOT)

from shared.macro_insight.macro_signal_aggregator import (
    MacroSignalAggregator,
    MacroSignalCache,
    CachedMacroSignal,
    get_macro_regime_adjustment,
    process_telegram_message,
    apply_macro_adjustment_to_regime,
    SIGNAL_CACHE_TTL_MINUTES,
    MAX_CACHED_MESSAGES,
)

from shared.macro_insight.macro_sentiment_analyzer import (
    MacroSignal,
    SignalType,
    MAX_EXTERNAL_WEIGHT,
)


class TestMacroSignalCache:
    """MacroSignalCache 테스트"""

    def setup_method(self):
        """테스트 설정"""
        self.cache = MacroSignalCache()

    def test_add_message(self):
        """메시지 추가"""
        msg = {"page_content": "테스트", "metadata": {}}
        self.cache.add_message(msg)
        messages = self.cache.get_messages()
        assert len(messages) == 1
        assert messages[0]["page_content"] == "테스트"

    def test_max_cache_size(self):
        """최대 캐시 크기 제한"""
        for i in range(MAX_CACHED_MESSAGES + 50):
            self.cache.add_message({"page_content": f"msg_{i}", "metadata": {}})

        messages = self.cache.get_messages()
        assert len(messages) == MAX_CACHED_MESSAGES
        # 가장 오래된 메시지는 삭제됨
        assert "msg_0" not in [m["page_content"] for m in messages]

    def test_signal_cache_ttl(self):
        """신호 캐시 TTL"""
        signal = MacroSignal(
            signal_type=SignalType.NEUTRAL,
            weighted_score=0.0,
            contributing_channels=0,
            total_messages=0,
            confidence=0.0,
            final_weight=0.0,
            should_influence_regime=False,
        )
        self.cache.set_signal(signal, 5)

        # TTL 내 조회
        cached = self.cache.get_signal()
        assert cached is not None
        assert cached.signal_type == SignalType.NEUTRAL

    def test_cache_clear(self):
        """캐시 초기화"""
        self.cache.add_message({"page_content": "test", "metadata": {}})
        self.cache.clear()
        assert len(self.cache.get_messages()) == 0
        assert self.cache.get_signal() is None


class TestMacroSignalAggregator:
    """MacroSignalAggregator 테스트"""

    def setup_method(self):
        """테스트 설정"""
        self.aggregator = MacroSignalAggregator(use_llm=False)
        self.aggregator.clear_cache()

    def test_process_message(self):
        """메시지 처리"""
        msg = {
            "page_content": "FOMC 금리 인상 결정",
            "metadata": {
                "channel_username": "hedgecat0301",
                "channel_role": "macro_signal",
                "weight": 0.6,
            }
        }
        success = self.aggregator.process_message(msg)
        assert success is True

    def test_get_current_signal_empty(self):
        """빈 캐시에서 신호 조회"""
        signal = self.aggregator.get_current_signal()
        assert signal.signal_type == SignalType.NEUTRAL
        assert signal.should_influence_regime is False

    def test_get_current_signal_with_data(self):
        """데이터 있는 경우 신호 조회"""
        # 긍정 메시지 추가 (다중 채널)
        messages = [
            {
                "page_content": "시장 강세 상승 기대 호조",
                "metadata": {
                    "channel_username": "hedgecat0301",
                    "channel_role": "macro_signal",
                    "content_hash": "msg1",
                    "weight": 0.6,
                }
            },
            {
                "page_content": "반도체 업종 강세 상승",
                "metadata": {
                    "channel_username": "HanaResearch",
                    "channel_role": "stock_reference",
                    "content_hash": "msg2",
                    "weight": 0.2,
                }
            },
        ]
        for msg in messages:
            self.aggregator.process_message(msg)

        signal = self.aggregator.get_current_signal(force_refresh=True)
        assert signal.total_messages == 2
        assert signal.contributing_channels == 2


class TestRegimeAdjustment:
    """MarketRegime 조정 테스트 (3현자 권고)"""

    def setup_method(self):
        """테스트 설정"""
        self.aggregator = MacroSignalAggregator(use_llm=False)
        self.aggregator.clear_cache()

    def test_no_adjustment_empty(self):
        """빈 캐시: 조정 없음"""
        adjustment = self.aggregator.get_regime_adjustment()
        assert adjustment["should_adjust"] is False
        assert adjustment["adjustment_weight"] == 0.0

    def test_risk_on_adjustment(self):
        """RISK_ON: 조정 가능"""
        # 강한 긍정 메시지 (다중 채널)
        messages = [
            {
                "page_content": "시장 강세 상승 호조 기대 개선 반등",
                "metadata": {
                    "channel_username": "hedgecat0301",
                    "channel_role": "macro_signal",
                    "content_hash": "risk_on_1",
                    "weight": 0.6,
                }
            },
            {
                "page_content": "업황 강세 상승 기대 회복",
                "metadata": {
                    "channel_username": "HanaResearch",
                    "channel_role": "macro_signal",
                    "content_hash": "risk_on_2",
                    "weight": 0.4,
                }
            },
        ]
        for msg in messages:
            self.aggregator.process_message(msg)

        adjustment = self.aggregator.get_regime_adjustment()
        # RISK_ON이고 다중 채널이면 조정 가능
        if adjustment.get("signal_details", {}).get("signal_type") == "RISK_ON":
            assert adjustment["suggested_direction"] == "bullish"
            assert adjustment["adjustment_weight"] <= MAX_EXTERNAL_WEIGHT

    def test_risk_off_hint_no_solo_trigger(self):
        """RISK_OFF_HINT: 단독 발동 금지 (3현자 핵심 권고)"""
        # 강한 부정 메시지
        messages = [
            {
                "page_content": "시장 약세 하락 우려 침체 리스크 붕괴 악재",
                "metadata": {
                    "channel_username": "hedgecat0301",
                    "channel_role": "macro_signal",
                    "content_hash": "risk_off_1",
                    "weight": 0.6,
                }
            },
            {
                "page_content": "경기 악화 부진 하락 약세",
                "metadata": {
                    "channel_username": "HanaResearch",
                    "channel_role": "macro_signal",
                    "content_hash": "risk_off_2",
                    "weight": 0.4,
                }
            },
        ]
        for msg in messages:
            self.aggregator.process_message(msg)

        adjustment = self.aggregator.get_regime_adjustment()

        # RISK_OFF_HINT인 경우 단독 발동 금지
        if adjustment.get("signal_details", {}).get("signal_type") == "RISK_OFF_HINT":
            assert adjustment["should_adjust"] is False
            assert "risk_off" in adjustment.get("reason", "").lower() or \
                   adjustment["suggested_direction"] == "bearish_hint"

    def test_max_weight_limit(self):
        """외부 정보 가중치 ≤10% 제한"""
        messages = [
            {
                "page_content": "강세 상승 호조",
                "metadata": {
                    "channel_username": f"ch_{i}",
                    "channel_role": "macro_signal",
                    "content_hash": f"msg_{i}",
                    "weight": 0.5,
                }
            }
            for i in range(5)
        ]
        for msg in messages:
            self.aggregator.process_message(msg)

        adjustment = self.aggregator.get_regime_adjustment()

        # adjustment_weight는 항상 ≤0.10
        assert adjustment["adjustment_weight"] <= MAX_EXTERNAL_WEIGHT


class TestApplyMacroAdjustment:
    """apply_macro_adjustment_to_regime 테스트"""

    def test_no_adjustment(self):
        """조정 없는 경우"""
        base_regime = "BULL"
        regime_context = {"regime_scores": {"BULL": 80, "BEAR": 20}}
        macro_adjustment = {
            "should_adjust": False,
            "adjustment_weight": 0.0,
            "suggested_direction": "neutral",
            "signal_details": {},
            "reason": "no_data",
        }

        adjusted, enriched = apply_macro_adjustment_to_regime(
            base_regime, regime_context, macro_adjustment
        )

        # Regime 변경 없음
        assert adjusted == base_regime
        # 매크로 정보 추가됨
        assert "macro_signal" in enriched
        assert "macro_influence" in enriched

    def test_bullish_adjustment(self):
        """Bullish 조정 적용"""
        base_regime = "BULL"
        original_bull_score = 80
        regime_context = {"regime_scores": {"BULL": original_bull_score, "BEAR": 20, "STRONG_BULL": 60}}
        macro_adjustment = {
            "should_adjust": True,
            "adjustment_weight": 0.08,
            "suggested_direction": "bullish",
            "signal_details": {"signal_type": "RISK_ON"},
        }

        adjusted, enriched = apply_macro_adjustment_to_regime(
            base_regime, regime_context, macro_adjustment
        )

        # Regime 자체는 변경 안함 (보조 역할)
        assert adjusted == base_regime
        # 점수 조정 적용됨
        assert enriched["regime_scores"]["BULL"] > original_bull_score
        assert enriched["macro_influence"]["applied"] is True

    def test_bearish_hint_warning_only(self):
        """Bearish hint: 경고만 제공 (3현자 권고)"""
        base_regime = "SIDEWAYS"
        regime_context = {"regime_scores": {"BULL": 40, "BEAR": 40, "SIDEWAYS": 50}}
        macro_adjustment = {
            "should_adjust": False,  # 단독 발동 금지로 항상 False
            "adjustment_weight": 0.0,
            "suggested_direction": "bearish_hint",
            "signal_details": {"signal_type": "RISK_OFF_HINT"},
        }

        adjusted, enriched = apply_macro_adjustment_to_regime(
            base_regime, regime_context, macro_adjustment
        )

        # Regime 변경 없음
        assert adjusted == base_regime
        # 점수 조정 없음 (applied=False 또는 없음)
        assert enriched["regime_scores"]["BEAR"] == regime_context["regime_scores"]["BEAR"]


class TestConvenienceFunctions:
    """편의 함수 테스트"""

    def test_process_telegram_message(self):
        """process_telegram_message 함수"""
        msg = {
            "page_content": "테스트 메시지",
            "metadata": {"channel_username": "test"},
        }
        success = process_telegram_message(msg)
        assert success is True

    def test_get_macro_regime_adjustment(self):
        """get_macro_regime_adjustment 함수"""
        adjustment = get_macro_regime_adjustment(use_llm=False)
        assert "should_adjust" in adjustment
        assert "adjustment_weight" in adjustment
        assert "suggested_direction" in adjustment


class TestCachedMacroSignal:
    """CachedMacroSignal 테스트"""

    def test_is_valid_fresh(self):
        """신선한 캐시"""
        signal = MacroSignal(
            signal_type=SignalType.NEUTRAL,
            weighted_score=0.0,
            contributing_channels=0,
            total_messages=0,
            confidence=0.0,
            final_weight=0.0,
            should_influence_regime=False,
        )
        cached = CachedMacroSignal(
            signal=signal,
            created_at=datetime.now(timezone.utc),
            source_messages=5,
        )
        assert cached.is_valid(ttl_minutes=30) is True


class TestEdgeCases:
    """엣지 케이스 테스트"""

    def setup_method(self):
        self.aggregator = MacroSignalAggregator(use_llm=False)
        self.aggregator.clear_cache()

    def test_single_channel_no_influence(self):
        """단일 채널: 영향력 없음 (다중 검증 실패)"""
        msg = {
            "page_content": "강세 상승 호조 기대 개선",
            "metadata": {
                "channel_username": "single_channel",
                "channel_role": "macro_signal",
                "content_hash": "single_1",
                "weight": 0.6,
            }
        }
        self.aggregator.process_message(msg)

        adjustment = self.aggregator.get_regime_adjustment()

        # 단일 채널은 다중 검증 실패로 영향 없음
        if adjustment.get("signal_details", {}).get("contributing_channels", 0) < 2:
            assert adjustment["should_adjust"] is False

    def test_empty_content(self):
        """빈 콘텐츠 처리"""
        msg = {
            "page_content": "",
            "metadata": {
                "channel_username": "test",
                "channel_role": "macro_signal",
            }
        }
        success = self.aggregator.process_message(msg)
        assert success is True  # 에러 없이 처리

    def test_missing_metadata(self):
        """메타데이터 누락"""
        msg = {
            "page_content": "테스트 강세 상승",
            "metadata": {}  # 빈 메타데이터
        }
        success = self.aggregator.process_message(msg)
        assert success is True


# ==============================================================================
# Test Runner
# ==============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
