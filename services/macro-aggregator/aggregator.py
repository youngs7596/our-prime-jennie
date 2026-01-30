#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
services/macro-aggregator/aggregator.py
---------------------------------------
Redis Stream에서 TelegramCollector 메시지를 소비하여
매크로 신호를 집계하는 서비스.

3현자 Council 권고사항:
- 외부 정보 가중치 ≤10%
- RISK_OFF 단독 발동 금지
- MarketRegimeDetector 보조 입력으로만 사용
"""

import os
import sys
import logging
import json
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, Any
from zoneinfo import ZoneInfo

# 프로젝트 루트 설정
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

# 한국 시간대
KST = ZoneInfo("Asia/Seoul")

from shared.messaging.stream_client import (
    consume_messages,
    ensure_consumer_group,
    STREAM_MACRO_RAW,
    GROUP_MACRO_ANALYZER,
)

from shared.macro_insight import (
    MacroSignalAggregator,
    MacroSignal,
    SignalType,
)

# ==============================================================================
# Logging
# ==============================================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger(__name__)

# ==============================================================================
# Configuration
# ==============================================================================

CONSUMER_NAME = os.getenv("MACRO_CONSUMER_NAME", "macro_aggregator_1")

# LLM 모드 설정
# - "auto": 시간대별 자동 전환 (장외 시간에만 LLM 사용)
# - "true": 항상 LLM 사용
# - "false": 항상 규칙 기반 사용
MACRO_LLM_MODE = os.getenv("MACRO_LLM_MODE", "auto").lower()

# 장외 시간 정의 (KST)
# - scout-job: 08:00~15:30 (30분 간격, ~25분 소요)
# - LLM 사용 가능 시간: 06:00~08:00, 16:00~24:00
LLM_WINDOW_MORNING_START = 6   # 06:00 KST
LLM_WINDOW_MORNING_END = 8     # 08:00 KST
LLM_WINDOW_EVENING_START = 16  # 16:00 KST (scout-job 완료 후)


def is_llm_available_time() -> bool:
    """
    현재 시간이 LLM 사용 가능 시간인지 확인.

    scout-job이 돌지 않는 시간대에만 gpt-oss LLM 사용:
    - 장 시작 전: 06:00 ~ 08:00 KST
    - 장 마감 후: 16:00 ~ 24:00 KST (+ 00:00 ~ 06:00)

    Returns:
        True if LLM can be used (scout-job not running)
    """
    now_kst = datetime.now(KST)
    hour = now_kst.hour

    # 장 시작 전 (06:00 ~ 08:00)
    if LLM_WINDOW_MORNING_START <= hour < LLM_WINDOW_MORNING_END:
        return True

    # 장 마감 후 (16:00 ~ 24:00) 또는 심야 (00:00 ~ 06:00)
    if hour >= LLM_WINDOW_EVENING_START or hour < LLM_WINDOW_MORNING_START:
        return True

    return False


def get_current_llm_mode() -> bool:
    """
    현재 LLM 사용 여부 결정.

    Returns:
        True if LLM should be used
    """
    if MACRO_LLM_MODE == "true":
        return True
    elif MACRO_LLM_MODE == "false":
        return False
    else:  # "auto" (기본값)
        return is_llm_available_time()

# ==============================================================================
# Message Handler
# ==============================================================================

# 전역 Aggregator 인스턴스 (동적 LLM 모드 지원)
_current_llm_mode: bool = get_current_llm_mode()
_aggregator = MacroSignalAggregator(use_llm=_current_llm_mode)


def _ensure_correct_llm_mode():
    """LLM 모드가 변경되었으면 Aggregator 재생성"""
    global _current_llm_mode, _aggregator

    new_mode = get_current_llm_mode()
    if new_mode != _current_llm_mode:
        old_mode_str = "LLM(gpt-oss)" if _current_llm_mode else "규칙기반"
        new_mode_str = "LLM(gpt-oss)" if new_mode else "규칙기반"
        logger.info(f"[MacroAggregator] 모드 전환: {old_mode_str} → {new_mode_str}")

        _current_llm_mode = new_mode
        # 기존 캐시 유지하면서 analyzer만 교체
        _aggregator = MacroSignalAggregator(use_llm=new_mode)


def handle_macro_message(page_content: str, metadata: Dict[str, Any]) -> bool:
    """
    Redis Stream 메시지 처리 핸들러.

    Args:
        page_content: 메시지 본문
        metadata: 메타데이터

    Returns:
        처리 성공 여부
    """
    try:
        # 시간대별 LLM 모드 체크 및 전환
        _ensure_correct_llm_mode()

        message = {
            "page_content": page_content,
            "metadata": metadata,
        }

        # Aggregator에 메시지 추가
        success = _aggregator.process_message(message)

        if success:
            channel = metadata.get("channel_username", "unknown")
            is_macro = metadata.get("is_macro_related", False)
            mode_str = "LLM" if _current_llm_mode else "규칙"
            logger.info(
                f"[MacroAggregator] 메시지 처리: @{channel}, "
                f"매크로관련={is_macro}, 모드={mode_str}"
            )

        return success

    except Exception as e:
        logger.error(f"[MacroAggregator] 핸들러 오류: {e}", exc_info=True)
        return False


def log_current_signal():
    """현재 매크로 신호 로깅"""
    try:
        # 시간대별 LLM 모드 체크 및 전환
        _ensure_correct_llm_mode()

        signal = _aggregator.get_current_signal()
        adjustment = _aggregator.get_regime_adjustment()
        mode_str = "LLM(gpt-oss)" if _current_llm_mode else "규칙기반"
        now_kst = datetime.now(KST).strftime("%H:%M KST")

        logger.info("=" * 60)
        logger.info("[MacroAggregator] 현재 매크로 신호 요약")
        logger.info("=" * 60)
        logger.info(f"  현재 시각: {now_kst}")
        logger.info(f"  분석 모드: {mode_str}")
        logger.info(f"  신호 유형: {signal.signal_type.value}")
        logger.info(f"  가중 점수: {signal.weighted_score:.3f}")
        logger.info(f"  기여 채널: {signal.contributing_channels}개")
        logger.info(f"  신뢰도: {signal.confidence:.2f}")
        logger.info(f"  최종 가중치: {signal.final_weight:.3f} (≤10%)")
        logger.info(f"  Regime 영향: {signal.should_influence_regime}")
        logger.info(f"  조정 방향: {adjustment.get('suggested_direction', 'N/A')}")
        logger.info("=" * 60)

    except Exception as e:
        logger.error(f"[MacroAggregator] 신호 로깅 오류: {e}")


# ==============================================================================
# Service Entry Points
# ==============================================================================

def run_consumer(max_iterations: int = None):
    """
    Redis Stream Consumer 실행.

    Args:
        max_iterations: 최대 반복 횟수 (None=무한)
    """
    current_mode = get_current_llm_mode()
    mode_str = "LLM(gpt-oss)" if current_mode else "규칙기반"
    now_kst = datetime.now(KST).strftime("%H:%M KST")

    logger.info("=" * 60)
    logger.info("[MacroAggregator] Consumer 시작")
    logger.info(f"  Stream: {STREAM_MACRO_RAW}")
    logger.info(f"  Group: {GROUP_MACRO_ANALYZER}")
    logger.info(f"  Consumer: {CONSUMER_NAME}")
    logger.info(f"  LLM 모드: {MACRO_LLM_MODE}")
    logger.info(f"  현재 모드: {mode_str} ({now_kst})")
    logger.info(f"  LLM 시간대: 06:00~08:00, 16:00~06:00 (KST)")
    logger.info("=" * 60)

    # Consumer Group 생성
    ensure_consumer_group(STREAM_MACRO_RAW, GROUP_MACRO_ANALYZER)

    # 메시지 소비 시작
    processed = consume_messages(
        group_name=GROUP_MACRO_ANALYZER,
        consumer_name=CONSUMER_NAME,
        handler=handle_macro_message,
        stream_name=STREAM_MACRO_RAW,
        batch_size=10,
        block_ms=2000,
        max_iterations=max_iterations,
    )

    logger.info(f"[MacroAggregator] Consumer 종료: 총 {processed}개 처리")
    return processed


def run_daemon(signal_interval_seconds: int = 300):
    """
    데몬 모드 실행.
    - Redis Stream Consumer 실행
    - 주기적으로 신호 요약 로깅

    Args:
        signal_interval_seconds: 신호 요약 로깅 주기 (초)
    """
    import threading

    logger.info("[MacroAggregator] Daemon 모드 시작")

    # 신호 로깅 스레드
    def signal_logger():
        while True:
            time.sleep(signal_interval_seconds)
            log_current_signal()

    log_thread = threading.Thread(target=signal_logger, daemon=True)
    log_thread.start()

    # Consumer 실행 (무한 루프)
    run_consumer(max_iterations=None)


def get_signal_summary() -> Dict[str, Any]:
    """
    현재 신호 요약 조회 (API/CLI용).

    Returns:
        {
            "signal": MacroSignal.to_dict(),
            "adjustment": regime_adjustment,
            "timestamp": ISO timestamp
        }
    """
    signal = _aggregator.get_current_signal()
    adjustment = _aggregator.get_regime_adjustment()

    return {
        "signal": signal.to_dict(),
        "adjustment": adjustment,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ==============================================================================
# CLI Entry Point
# ==============================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Macro Aggregator Service")
    parser.add_argument("--daemon", action="store_true", help="Run as daemon")
    parser.add_argument("--signal-interval", type=int, default=300, help="Signal logging interval (seconds)")
    parser.add_argument("--max-iterations", type=int, default=None, help="Max iterations (for testing)")
    parser.add_argument("--summary", action="store_true", help="Print current signal summary and exit")
    parser.add_argument(
        "--llm-mode",
        choices=["auto", "true", "false"],
        default=None,
        help="LLM mode: auto (시간대별), true (항상), false (규칙기반)"
    )
    args = parser.parse_args()

    # CLI 인자로 LLM 모드 오버라이드
    if args.llm_mode:
        MACRO_LLM_MODE = args.llm_mode
        _current_llm_mode = get_current_llm_mode()
        _aggregator = MacroSignalAggregator(use_llm=_current_llm_mode)
        logger.info(f"[MacroAggregator] LLM 모드 오버라이드: {args.llm_mode}")

    if args.summary:
        summary = get_signal_summary()
        print(json.dumps(summary, indent=2, ensure_ascii=False))
    elif args.daemon:
        run_daemon(args.signal_interval)
    else:
        run_consumer(max_iterations=args.max_iterations)
