#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
shared/macro_data/monitoring.py
-------------------------------
정확도 추적 및 롤백 메커니즘.

3현자 Council 요구사항:
- 10%p 예측 정확도 개선 목표
- 사실 오류 10% 이상 시 자동 롤백
"""

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, date, timedelta
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import redis

logger = logging.getLogger(__name__)

KST = ZoneInfo("Asia/Seoul")


@dataclass
class AccuracyRecord:
    """정확도 기록"""
    record_date: date
    total_predictions: int = 0
    correct_predictions: int = 0
    error_count: int = 0
    error_details: List[str] = field(default_factory=list)

    @property
    def accuracy_rate(self) -> float:
        """정확도 비율"""
        if self.total_predictions == 0:
            return 0.0
        return self.correct_predictions / self.total_predictions

    @property
    def error_rate(self) -> float:
        """오류율"""
        if self.total_predictions == 0:
            return 0.0
        return self.error_count / self.total_predictions

    def to_dict(self) -> Dict[str, Any]:
        return {
            "record_date": self.record_date.isoformat(),
            "total_predictions": self.total_predictions,
            "correct_predictions": self.correct_predictions,
            "error_count": self.error_count,
            "error_details": self.error_details,
            "accuracy_rate": self.accuracy_rate,
            "error_rate": self.error_rate,
        }


class AccuracyTracker:
    """
    정확도 추적기.

    3현자 요구사항:
    - 10%p 예측 정확도 개선 목표 추적
    - 일일/주간/월간 통계

    Usage:
        tracker = AccuracyTracker()
        tracker.record_prediction("sentiment", predicted="bullish", actual="bullish")
        tracker.record_error("데이터 타임스탬프 오류")
        stats = tracker.get_stats()
    """

    REDIS_KEY_PREFIX = "macro:accuracy:"
    REDIS_KEY_DAILY = "macro:accuracy:daily:"
    REDIS_KEY_ERRORS = "macro:accuracy:errors:"

    def __init__(self, redis_url: Optional[str] = None):
        """
        초기화.

        Args:
            redis_url: Redis URL (없으면 환경변수에서)
        """
        self.redis_url = redis_url or os.getenv(
            "REDIS_URL", "redis://localhost:6379/0"
        )
        self._client: Optional[redis.Redis] = None

    @property
    def client(self) -> redis.Redis:
        """Redis 클라이언트"""
        if self._client is None:
            self._client = redis.from_url(self.redis_url)
        return self._client

    def _get_today_key(self) -> str:
        """오늘 날짜 키"""
        return f"{self.REDIS_KEY_DAILY}{date.today().isoformat()}"

    def record_prediction(
        self,
        category: str,
        predicted: Any,
        actual: Any,
        metadata: Optional[Dict] = None
    ) -> bool:
        """
        예측 결과 기록.

        Args:
            category: 예측 카테고리 (sentiment, regime, sector 등)
            predicted: 예측값
            actual: 실제값
            metadata: 추가 메타데이터

        Returns:
            기록 성공 여부
        """
        try:
            key = self._get_today_key()
            is_correct = predicted == actual

            # 카운터 증가
            self.client.hincrby(key, "total_predictions", 1)
            if is_correct:
                self.client.hincrby(key, "correct_predictions", 1)

            # 카테고리별 통계
            cat_key = f"{key}:{category}"
            self.client.hincrby(cat_key, "total", 1)
            if is_correct:
                self.client.hincrby(cat_key, "correct", 1)

            # TTL 설정 (30일)
            self.client.expire(key, 30 * 24 * 3600)
            self.client.expire(cat_key, 30 * 24 * 3600)

            logger.debug(
                f"[AccuracyTracker] Recorded: {category} - "
                f"predicted={predicted}, actual={actual}, correct={is_correct}"
            )

            return True

        except Exception as e:
            logger.error(f"[AccuracyTracker] Record prediction failed: {e}")
            return False

    def record_error(
        self,
        error_description: str,
        error_type: str = "general",
        metadata: Optional[Dict] = None
    ) -> bool:
        """
        오류 기록.

        Args:
            error_description: 오류 설명
            error_type: 오류 유형
            metadata: 추가 메타데이터

        Returns:
            기록 성공 여부
        """
        try:
            key = self._get_today_key()
            error_key = f"{self.REDIS_KEY_ERRORS}{date.today().isoformat()}"

            # 에러 카운터 증가
            self.client.hincrby(key, "error_count", 1)

            # 에러 상세 저장
            error_data = {
                "timestamp": datetime.now(KST).isoformat(),
                "type": error_type,
                "description": error_description,
                "metadata": metadata or {},
            }
            self.client.lpush(error_key, json.dumps(error_data, ensure_ascii=False))

            # 최대 100개 유지
            self.client.ltrim(error_key, 0, 99)

            # TTL 설정
            self.client.expire(error_key, 30 * 24 * 3600)

            logger.warning(f"[AccuracyTracker] Error recorded: {error_description}")

            return True

        except Exception as e:
            logger.error(f"[AccuracyTracker] Record error failed: {e}")
            return False

    def get_today_stats(self) -> AccuracyRecord:
        """오늘 통계 조회"""
        try:
            key = self._get_today_key()
            data = self.client.hgetall(key)

            if not data:
                return AccuracyRecord(record_date=date.today())

            return AccuracyRecord(
                record_date=date.today(),
                total_predictions=int(data.get(b"total_predictions", 0)),
                correct_predictions=int(data.get(b"correct_predictions", 0)),
                error_count=int(data.get(b"error_count", 0)),
            )

        except Exception as e:
            logger.error(f"[AccuracyTracker] Get today stats failed: {e}")
            return AccuracyRecord(record_date=date.today())

    def get_weekly_stats(self) -> List[AccuracyRecord]:
        """주간 통계 조회"""
        records = []
        today = date.today()

        for i in range(7):
            target_date = today - timedelta(days=i)
            key = f"{self.REDIS_KEY_DAILY}{target_date.isoformat()}"

            try:
                data = self.client.hgetall(key)
                if data:
                    records.append(AccuracyRecord(
                        record_date=target_date,
                        total_predictions=int(data.get(b"total_predictions", 0)),
                        correct_predictions=int(data.get(b"correct_predictions", 0)),
                        error_count=int(data.get(b"error_count", 0)),
                    ))
            except Exception as e:
                logger.warning(f"[AccuracyTracker] Get stats for {target_date} failed: {e}")

        return records

    def get_error_rate(self, days: int = 7) -> float:
        """
        최근 N일간 오류율 계산.

        Args:
            days: 조회 기간

        Returns:
            오류율 (0.0 ~ 1.0)
        """
        total_predictions = 0
        total_errors = 0

        for record in self.get_weekly_stats()[:days]:
            total_predictions += record.total_predictions
            total_errors += record.error_count

        if total_predictions == 0:
            return 0.0

        return total_errors / total_predictions

    def get_accuracy_improvement(self, baseline_date: Optional[date] = None) -> float:
        """
        정확도 개선율 계산.

        Args:
            baseline_date: 기준 날짜 (없으면 30일 전)

        Returns:
            개선율 (%p)
        """
        # TODO: 구현 (히스토리 데이터 필요)
        return 0.0


class MacroInsightRollback:
    """
    Enhanced Macro Insight 롤백 메커니즘.

    3현자 요구사항:
    - 사실 오류 10% 초과 시 자동 롤백
    - Redis 플래그로 기능 비활성화
    """

    REDIS_KEY_ENABLED = "macro:enhanced:enabled"
    REDIS_KEY_ROLLBACK_HISTORY = "macro:enhanced:rollback_history"
    ERROR_THRESHOLD = 0.10  # 10%

    def __init__(self, redis_url: Optional[str] = None):
        """
        초기화.

        Args:
            redis_url: Redis URL
        """
        self.redis_url = redis_url or os.getenv(
            "REDIS_URL", "redis://localhost:6379/0"
        )
        self._client: Optional[redis.Redis] = None
        self._tracker = AccuracyTracker(redis_url)

    @property
    def client(self) -> redis.Redis:
        """Redis 클라이언트"""
        if self._client is None:
            self._client = redis.from_url(self.redis_url)
        return self._client

    def is_enabled(self) -> bool:
        """
        Enhanced Macro 기능 활성화 여부.

        Returns:
            True if enabled
        """
        try:
            value = self.client.get(self.REDIS_KEY_ENABLED)
            if value is None:
                return True  # 기본값: 활성화
            return value.decode().lower() == "true"
        except Exception as e:
            logger.error(f"[Rollback] Check enabled failed: {e}")
            return True

    def enable(self, reason: str = "") -> bool:
        """
        기능 활성화.

        Args:
            reason: 활성화 이유

        Returns:
            성공 여부
        """
        try:
            self.client.set(self.REDIS_KEY_ENABLED, "true")

            # 히스토리 기록
            history = {
                "action": "enable",
                "timestamp": datetime.now(KST).isoformat(),
                "reason": reason,
            }
            self.client.lpush(
                self.REDIS_KEY_ROLLBACK_HISTORY,
                json.dumps(history, ensure_ascii=False)
            )

            logger.info(f"[Rollback] Enhanced Macro ENABLED: {reason}")
            return True

        except Exception as e:
            logger.error(f"[Rollback] Enable failed: {e}")
            return False

    def disable(self, reason: str = "") -> bool:
        """
        기능 비활성화 (롤백).

        Args:
            reason: 비활성화 이유

        Returns:
            성공 여부
        """
        try:
            self.client.set(self.REDIS_KEY_ENABLED, "false")

            # 히스토리 기록
            history = {
                "action": "disable",
                "timestamp": datetime.now(KST).isoformat(),
                "reason": reason,
            }
            self.client.lpush(
                self.REDIS_KEY_ROLLBACK_HISTORY,
                json.dumps(history, ensure_ascii=False)
            )

            logger.warning(f"[Rollback] Enhanced Macro DISABLED: {reason}")

            # 텔레그램 알림 (선택적)
            self._send_rollback_alert(reason)

            return True

        except Exception as e:
            logger.error(f"[Rollback] Disable failed: {e}")
            return False

    def check_and_rollback(self) -> bool:
        """
        오류율 확인 및 자동 롤백.

        3현자 권고: 사실 오류 10% 이상 시 자동 롤백

        Returns:
            True if rollback triggered
        """
        error_rate = self._tracker.get_error_rate(days=7)

        if error_rate > self.ERROR_THRESHOLD:
            reason = (
                f"Error rate ({error_rate:.1%}) exceeded threshold "
                f"({self.ERROR_THRESHOLD:.1%}). Auto-rollback triggered."
            )
            self.disable(reason)
            return True

        return False

    def get_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        롤백 히스토리 조회.

        Args:
            limit: 최대 조회 수

        Returns:
            히스토리 리스트
        """
        try:
            raw_history = self.client.lrange(
                self.REDIS_KEY_ROLLBACK_HISTORY, 0, limit - 1
            )

            history = []
            for item in raw_history:
                try:
                    history.append(json.loads(item))
                except json.JSONDecodeError:
                    continue

            return history

        except Exception as e:
            logger.error(f"[Rollback] Get history failed: {e}")
            return []

    def get_status(self) -> Dict[str, Any]:
        """
        현재 상태 조회.

        Returns:
            상태 정보 딕셔너리
        """
        stats = self._tracker.get_today_stats()
        error_rate = self._tracker.get_error_rate(days=7)

        return {
            "enabled": self.is_enabled(),
            "error_threshold": self.ERROR_THRESHOLD,
            "current_error_rate": error_rate,
            "would_rollback": error_rate > self.ERROR_THRESHOLD,
            "today_stats": stats.to_dict(),
            "last_actions": self.get_history(3),
        }

    def _send_rollback_alert(self, reason: str) -> None:
        """텔레그램 롤백 알림 전송"""
        try:
            # 텔레그램 알림 (선택적 구현)
            logger.info(f"[Rollback] Alert sent: {reason}")
        except Exception as e:
            logger.warning(f"[Rollback] Alert failed: {e}")


# 글로벌 인스턴스
_tracker: Optional[AccuracyTracker] = None
_rollback: Optional[MacroInsightRollback] = None


def get_accuracy_tracker() -> AccuracyTracker:
    """글로벌 AccuracyTracker 인스턴스"""
    global _tracker
    if _tracker is None:
        _tracker = AccuracyTracker()
    return _tracker


def get_rollback_manager() -> MacroInsightRollback:
    """글로벌 Rollback 인스턴스"""
    global _rollback
    if _rollback is None:
        _rollback = MacroInsightRollback()
    return _rollback


def is_enhanced_macro_enabled() -> bool:
    """Enhanced Macro 활성화 여부 (편의 함수)"""
    return get_rollback_manager().is_enabled()
