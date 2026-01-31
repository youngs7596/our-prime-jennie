"""
shared/deploy_safety.py - 배포 안전장치 모듈
==========================================

배포 중 트레이딩 안전을 보장하기 위한 유틸리티.

주요 기능:
---------
1. 배포 시 자동 Trading Pause 설정/해제
2. 배포 상태 추적
3. 비상 정지 기능

사용 예시:
---------
>>> from shared.deploy_safety import DeploySafetyGuard
>>>
>>> # 배포 시작 시
>>> with DeploySafetyGuard(redis_url="redis://localhost:6379/0"):
...     # 이 블록 동안 trading_pause=True
...     deploy_services()
...
>>> # 블록 종료 시 자동으로 trading_pause=False

환경변수:
--------
- REDIS_URL: Redis 연결 URL
- DEPLOY_PAUSE_ENABLED: true면 배포 시 자동 pause (기본: true)
"""

import logging
import os
import time
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# 배포 관련 Redis 키
DEPLOY_STATE_KEY = "deploy:state"
DEPLOY_START_TIME_KEY = "deploy:start_time"
DEPLOY_SERVICE_KEY = "deploy:current_service"
TRADING_PAUSE_KEY = "trading:pause"
TRADING_PAUSE_REASON_KEY = "trading:pause_reason"


class DeploySafetyGuard:
    """
    배포 안전장치 컨텍스트 매니저

    배포 시작 시 트레이딩을 일시 중지하고,
    배포 완료 후 자동으로 재개합니다.
    """

    def __init__(
        self,
        redis_url: Optional[str] = None,
        pause_on_deploy: bool = True,
        deployment_id: Optional[str] = None
    ):
        """
        Args:
            redis_url: Redis 연결 URL
            pause_on_deploy: True면 배포 시 자동 pause
            deployment_id: 배포 식별자 (로깅용)
        """
        self.redis_url = redis_url or os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self.pause_on_deploy = pause_on_deploy and os.getenv(
            "DEPLOY_PAUSE_ENABLED", "true"
        ).lower() == "true"
        self.deployment_id = deployment_id or f"deploy-{int(time.time())}"
        self._redis = None
        self._previous_pause_state = None

    def _get_redis(self):
        """Redis 연결 반환 (Lazy initialization)"""
        if self._redis is None:
            import redis
            self._redis = redis.from_url(self.redis_url, decode_responses=True)
        return self._redis

    def __enter__(self):
        """배포 시작: Trading Pause 설정"""
        if not self.pause_on_deploy:
            logger.info("[DeploySafety] 배포 pause 비활성화 상태")
            return self

        try:
            r = self._get_redis()

            # 기존 pause 상태 저장
            self._previous_pause_state = r.get(TRADING_PAUSE_KEY)

            # Trading Pause 설정
            r.set(TRADING_PAUSE_KEY, "true")
            r.set(TRADING_PAUSE_REASON_KEY, f"deployment:{self.deployment_id}")
            r.set(DEPLOY_STATE_KEY, "in_progress")
            r.set(DEPLOY_START_TIME_KEY, datetime.now().isoformat())

            logger.info(
                "🚧 [DeploySafety] 배포 시작 - Trading Pause 활성화 (id=%s)",
                self.deployment_id
            )

        except Exception as e:
            logger.error(
                "[DeploySafety] Trading Pause 설정 실패: %s (배포는 계속 진행)",
                e
            )

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """배포 종료: Trading Pause 해제"""
        if not self.pause_on_deploy:
            return False

        try:
            r = self._get_redis()

            # Trading Pause 해제 (기존 상태가 pause가 아니었으면)
            if self._previous_pause_state != "true":
                r.delete(TRADING_PAUSE_KEY)
                r.delete(TRADING_PAUSE_REASON_KEY)

            # 배포 상태 업데이트
            if exc_type is None:
                r.set(DEPLOY_STATE_KEY, "completed")
                logger.info(
                    "✅ [DeploySafety] 배포 완료 - Trading Pause 해제 (id=%s)",
                    self.deployment_id
                )
            else:
                r.set(DEPLOY_STATE_KEY, f"failed:{exc_type.__name__}")
                logger.warning(
                    "⚠️ [DeploySafety] 배포 실패 - Trading Pause 해제 (id=%s, error=%s)",
                    self.deployment_id, exc_type.__name__
                )

        except Exception as e:
            logger.error(
                "[DeploySafety] Trading Pause 해제 실패: %s (수동 확인 필요)",
                e
            )

        return False  # 예외 전파

    def mark_service_deploying(self, service_name: str):
        """현재 배포 중인 서비스 기록"""
        try:
            r = self._get_redis()
            r.set(DEPLOY_SERVICE_KEY, service_name)
            logger.info("[DeploySafety] 서비스 배포 중: %s", service_name)
        except Exception as e:
            logger.warning("[DeploySafety] 서비스 마킹 실패: %s", e)

    def mark_service_completed(self, service_name: str):
        """서비스 배포 완료 기록"""
        try:
            r = self._get_redis()
            current = r.get(DEPLOY_SERVICE_KEY)
            if current == service_name:
                r.delete(DEPLOY_SERVICE_KEY)
            logger.info("[DeploySafety] 서비스 배포 완료: %s", service_name)
        except Exception as e:
            logger.warning("[DeploySafety] 서비스 완료 마킹 실패: %s", e)


def set_trading_pause(paused: bool, reason: str = "manual") -> bool:
    """
    트레이딩 일시 중지 설정 (모듈 레벨 함수)

    Args:
        paused: True면 pause, False면 resume
        reason: 사유 (로깅용)

    Returns:
        성공 여부
    """
    try:
        import redis
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        r = redis.from_url(redis_url, decode_responses=True)

        if paused:
            r.set(TRADING_PAUSE_KEY, "true")
            r.set(TRADING_PAUSE_REASON_KEY, reason)
            logger.info("🚧 Trading Pause 설정 (reason=%s)", reason)
        else:
            r.delete(TRADING_PAUSE_KEY)
            r.delete(TRADING_PAUSE_REASON_KEY)
            logger.info("✅ Trading Pause 해제 (reason=%s)", reason)

        return True

    except Exception as e:
        logger.error("Trading Pause 설정 실패: %s", e)
        return False


def is_deployment_in_progress() -> bool:
    """배포 진행 중인지 확인"""
    try:
        import redis
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        r = redis.from_url(redis_url, decode_responses=True)

        state = r.get(DEPLOY_STATE_KEY)
        return state == "in_progress"

    except Exception as e:
        logger.warning("배포 상태 확인 실패: %s", e)
        return False


def get_deployment_info() -> dict:
    """현재 배포 정보 조회"""
    try:
        import redis
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        r = redis.from_url(redis_url, decode_responses=True)

        return {
            "state": r.get(DEPLOY_STATE_KEY),
            "start_time": r.get(DEPLOY_START_TIME_KEY),
            "current_service": r.get(DEPLOY_SERVICE_KEY),
            "trading_paused": r.get(TRADING_PAUSE_KEY) == "true",
            "pause_reason": r.get(TRADING_PAUSE_REASON_KEY)
        }

    except Exception as e:
        logger.warning("배포 정보 조회 실패: %s", e)
        return {}
