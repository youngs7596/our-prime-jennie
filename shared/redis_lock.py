# shared/redis_lock.py
# Distributed Lock using Redis
# 표준화된 분산 락 구현 - buy-executor, sell-executor 공용

import logging
from contextlib import contextmanager
from typing import Optional

logger = logging.getLogger(__name__)


class DistributedLock:
    """
    Redis 기반 분산 락 (Context Manager)

    사용 예:
        from shared.redis_lock import DistributedLock
        from shared.redis_cache import get_redis_connection

        redis = get_redis_connection()
        with DistributedLock(redis, "lock:buy:005930", ttl=60) as acquired:
            if acquired:
                # 락 획득 성공 - 작업 수행
                process_order()
            else:
                # 락 획득 실패 - 중복 실행 방지
                return {"status": "skipped", "reason": "Duplicate lock"}
    """

    def __init__(self, redis_client, lock_key: str, ttl: int = 60):
        """
        Args:
            redis_client: Redis 연결 객체
            lock_key: 락 키 (예: "lock:buy:005930")
            ttl: 락 TTL (초), 기본 60초
        """
        self.redis = redis_client
        self.lock_key = lock_key
        self.ttl = ttl
        self.acquired = False

    def __enter__(self) -> bool:
        """락 획득 시도"""
        if not self.redis:
            logger.warning(f"[Lock] Redis 연결 없음 - 락 생략: {self.lock_key}")
            return True  # Redis 없으면 통과 (fail-open)

        try:
            # NX: 키가 없을 때만 설정, EX: TTL 설정
            self.acquired = self.redis.set(self.lock_key, "LOCKED", nx=True, ex=self.ttl)
            if self.acquired:
                logger.debug(f"[Lock] 락 획득 성공: {self.lock_key} (TTL={self.ttl}s)")
            else:
                logger.warning(f"[Lock] 락 획득 실패 (이미 잠김): {self.lock_key}")
            return self.acquired
        except Exception as e:
            logger.error(f"[Lock] 락 획득 중 오류: {e}")
            return False

    def __exit__(self, exc_type, exc_val, exc_tb):
        """락 해제"""
        if self.acquired and self.redis:
            try:
                self.redis.delete(self.lock_key)
                logger.debug(f"[Lock] 락 해제 완료: {self.lock_key}")
            except Exception as e:
                logger.warning(f"[Lock] 락 해제 실패 (TTL 만료 대기): {e}")
        return False  # 예외 전파


@contextmanager
def distributed_lock(lock_key: str, ttl: int = 60, redis_client=None):
    """
    분산 락 함수형 컨텍스트 매니저

    사용 예:
        from shared.redis_lock import distributed_lock

        with distributed_lock("lock:buy:005930") as acquired:
            if acquired:
                process_order()

    Args:
        lock_key: 락 키
        ttl: 락 TTL (초)
        redis_client: Redis 연결 (None이면 자동 조회)

    Yields:
        bool: 락 획득 성공 여부
    """
    if redis_client is None:
        from shared.redis_cache import get_redis_connection
        redis_client = get_redis_connection()

    lock = DistributedLock(redis_client, lock_key, ttl)
    try:
        yield lock.__enter__()
    finally:
        lock.__exit__(None, None, None)


def acquire_lock(lock_key: str, ttl: int = 60, redis_client=None) -> bool:
    """
    단순 락 획득 (컨텍스트 매니저 없이)

    주의: 이 함수를 사용하면 release_lock을 직접 호출해야 합니다.

    Args:
        lock_key: 락 키
        ttl: 락 TTL (초)
        redis_client: Redis 연결

    Returns:
        bool: 락 획득 성공 여부
    """
    if redis_client is None:
        from shared.redis_cache import get_redis_connection
        redis_client = get_redis_connection()

    if not redis_client:
        return True  # fail-open

    try:
        return redis_client.set(lock_key, "LOCKED", nx=True, ex=ttl)
    except Exception as e:
        logger.error(f"[Lock] 락 획득 오류: {e}")
        return False


def release_lock(lock_key: str, redis_client=None) -> bool:
    """
    락 해제

    Args:
        lock_key: 락 키
        redis_client: Redis 연결

    Returns:
        bool: 락 해제 성공 여부
    """
    if redis_client is None:
        from shared.redis_cache import get_redis_connection
        redis_client = get_redis_connection()

    if not redis_client:
        return True

    try:
        redis_client.delete(lock_key)
        return True
    except Exception as e:
        logger.warning(f"[Lock] 락 해제 오류: {e}")
        return False
