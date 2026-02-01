#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
shared/macro_data/cache.py
--------------------------
Redis 캐시 레이어.

API 응답을 캐시하여 rate limit 절약 및 성능 향상.
"""

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, TypeVar, Generic
import redis

from .models import MacroDataPoint, GlobalMacroSnapshot, IndicatorCategory

logger = logging.getLogger(__name__)

T = TypeVar('T')


@dataclass
class CacheConfig:
    """캐시 설정"""
    default_ttl: int = 3600       # 기본 TTL (1시간)
    snapshot_ttl: int = 21600     # 스냅샷 TTL (6시간)
    news_ttl: int = 1800          # 뉴스 TTL (30분)
    indicator_ttl: int = 7200     # 지표 TTL (2시간)


class MacroDataCache:
    """
    매크로 데이터 Redis 캐시.

    Usage:
        cache = MacroDataCache()

        # 데이터 포인트 캐시
        cache.set_data_point("finnhub", "vix", point)
        point = cache.get_data_point("finnhub", "vix")

        # 스냅샷 캐시
        cache.set_snapshot(snapshot)
        snapshot = cache.get_snapshot()
    """

    # Redis 키 프리픽스
    KEY_PREFIX = "macro:data:"
    KEY_POINT = "macro:data:point:"
    KEY_SNAPSHOT = "macro:data:snapshot"
    KEY_NEWS = "macro:data:news:"
    KEY_LAST_FETCH = "macro:data:last_fetch:"

    def __init__(
        self,
        redis_url: Optional[str] = None,
        config: Optional[CacheConfig] = None
    ):
        """
        캐시 초기화.

        Args:
            redis_url: Redis URL (없으면 환경변수에서)
            config: 캐시 설정
        """
        self.redis_url = redis_url or os.getenv(
            "REDIS_URL", "redis://localhost:6379/0"
        )
        self.config = config or CacheConfig()
        self._client: Optional[redis.Redis] = None

    @property
    def client(self) -> redis.Redis:
        """Redis 클라이언트 (lazy init)"""
        if self._client is None:
            self._client = redis.from_url(self.redis_url)
        return self._client

    def _serialize(self, obj: Any) -> str:
        """객체 직렬화"""
        if hasattr(obj, 'to_dict'):
            return json.dumps(obj.to_dict(), ensure_ascii=False, default=str)
        return json.dumps(obj, ensure_ascii=False, default=str)

    def _deserialize_data_point(self, data: str) -> MacroDataPoint:
        """MacroDataPoint 역직렬화"""
        d = json.loads(data)
        return MacroDataPoint(
            indicator=d["indicator"],
            value=d["value"],
            timestamp=datetime.fromisoformat(d["timestamp"]),
            source=d["source"],
            category=IndicatorCategory(d.get("category", "us_economy")),
            unit=d.get("unit", ""),
            metadata=d.get("metadata", {}),
        )

    # =========================================================================
    # Data Point Operations
    # =========================================================================

    def set_data_point(
        self,
        source: str,
        indicator: str,
        point: MacroDataPoint,
        ttl: Optional[int] = None
    ) -> bool:
        """
        데이터 포인트 캐시 저장.

        Args:
            source: 데이터 소스
            indicator: 지표 이름
            point: MacroDataPoint
            ttl: TTL (초)

        Returns:
            저장 성공 여부
        """
        try:
            key = f"{self.KEY_POINT}{source}:{indicator}"
            ttl = ttl or self.config.indicator_ttl

            self.client.set(key, self._serialize(point), ex=ttl)

            logger.debug(f"[Cache] Set {key} (TTL: {ttl}s)")
            return True

        except Exception as e:
            logger.error(f"[Cache] Set data point failed: {e}")
            return False

    def get_data_point(
        self,
        source: str,
        indicator: str
    ) -> Optional[MacroDataPoint]:
        """
        데이터 포인트 캐시 조회.

        Args:
            source: 데이터 소스
            indicator: 지표 이름

        Returns:
            MacroDataPoint 또는 None
        """
        try:
            key = f"{self.KEY_POINT}{source}:{indicator}"
            data = self.client.get(key)

            if data:
                point = self._deserialize_data_point(data)
                logger.debug(f"[Cache] Hit {key}")
                return point

            logger.debug(f"[Cache] Miss {key}")
            return None

        except Exception as e:
            logger.error(f"[Cache] Get data point failed: {e}")
            return None

    def get_all_data_points(
        self,
        source: Optional[str] = None
    ) -> List[MacroDataPoint]:
        """
        모든 캐시된 데이터 포인트 조회.

        Args:
            source: 특정 소스만 (None이면 전체)

        Returns:
            MacroDataPoint 리스트
        """
        try:
            pattern = f"{self.KEY_POINT}{source or '*'}:*"
            points = []

            cursor = 0
            while True:
                cursor, keys = self.client.scan(
                    cursor=cursor, match=pattern, count=100
                )
                for key in keys:
                    data = self.client.get(key)
                    if data:
                        points.append(self._deserialize_data_point(data))

                if cursor == 0:
                    break

            return points

        except Exception as e:
            logger.error(f"[Cache] Get all data points failed: {e}")
            return []

    # =========================================================================
    # Snapshot Operations
    # =========================================================================

    def set_snapshot(
        self,
        snapshot: GlobalMacroSnapshot,
        ttl: Optional[int] = None
    ) -> bool:
        """
        스냅샷 캐시 저장.

        Args:
            snapshot: GlobalMacroSnapshot
            ttl: TTL (초)

        Returns:
            저장 성공 여부
        """
        try:
            key = self.KEY_SNAPSHOT
            date_key = f"{self.KEY_SNAPSHOT}:{snapshot.snapshot_date.isoformat()}"
            ttl = ttl or self.config.snapshot_ttl

            data = self._serialize(snapshot)

            # 현재 스냅샷
            self.client.set(key, data, ex=ttl)

            # 날짜별 스냅샷 (7일 보관)
            self.client.set(date_key, data, ex=7 * 24 * 3600)

            logger.info(f"[Cache] Snapshot saved: {snapshot.snapshot_date}")
            return True

        except Exception as e:
            logger.error(f"[Cache] Set snapshot failed: {e}")
            return False

    def get_snapshot(self) -> Optional[GlobalMacroSnapshot]:
        """
        현재 스냅샷 캐시 조회.

        Returns:
            GlobalMacroSnapshot 또는 None
        """
        try:
            data = self.client.get(self.KEY_SNAPSHOT)

            if data:
                d = json.loads(data)
                return GlobalMacroSnapshot.from_dict(d)

            return None

        except Exception as e:
            logger.error(f"[Cache] Get snapshot failed: {e}")
            return None

    def get_snapshot_by_date(
        self,
        target_date: datetime.date
    ) -> Optional[GlobalMacroSnapshot]:
        """
        특정 날짜 스냅샷 조회.

        Args:
            target_date: 조회할 날짜

        Returns:
            GlobalMacroSnapshot 또는 None
        """
        try:
            key = f"{self.KEY_SNAPSHOT}:{target_date.isoformat()}"
            data = self.client.get(key)

            if data:
                d = json.loads(data)
                return GlobalMacroSnapshot.from_dict(d)

            return None

        except Exception as e:
            logger.error(f"[Cache] Get snapshot by date failed: {e}")
            return None

    # =========================================================================
    # News Operations
    # =========================================================================

    def set_news(
        self,
        source: str,
        news_items: List[Dict[str, Any]],
        ttl: Optional[int] = None
    ) -> bool:
        """
        뉴스 캐시 저장.

        Args:
            source: 뉴스 소스
            news_items: 뉴스 아이템 리스트
            ttl: TTL (초)

        Returns:
            저장 성공 여부
        """
        try:
            key = f"{self.KEY_NEWS}{source}"
            ttl = ttl or self.config.news_ttl

            data = json.dumps(news_items, ensure_ascii=False, default=str)
            self.client.set(key, data, ex=ttl)

            logger.debug(f"[Cache] News saved: {source} ({len(news_items)} items)")
            return True

        except Exception as e:
            logger.error(f"[Cache] Set news failed: {e}")
            return False

    def get_news(self, source: str) -> List[Dict[str, Any]]:
        """
        뉴스 캐시 조회.

        Args:
            source: 뉴스 소스

        Returns:
            뉴스 아이템 리스트
        """
        try:
            key = f"{self.KEY_NEWS}{source}"
            data = self.client.get(key)

            if data:
                return json.loads(data)

            return []

        except Exception as e:
            logger.error(f"[Cache] Get news failed: {e}")
            return []

    # =========================================================================
    # Last Fetch Tracking
    # =========================================================================

    def set_last_fetch(self, source: str) -> None:
        """마지막 fetch 시간 기록"""
        try:
            key = f"{self.KEY_LAST_FETCH}{source}"
            self.client.set(key, datetime.now().isoformat(), ex=86400)
        except Exception as e:
            logger.error(f"[Cache] Set last fetch failed: {e}")

    def get_last_fetch(self, source: str) -> Optional[datetime]:
        """마지막 fetch 시간 조회"""
        try:
            key = f"{self.KEY_LAST_FETCH}{source}"
            data = self.client.get(key)

            if data:
                return datetime.fromisoformat(data.decode() if isinstance(data, bytes) else data)

            return None

        except Exception as e:
            logger.error(f"[Cache] Get last fetch failed: {e}")
            return None

    def should_fetch(self, source: str, min_interval_seconds: int = 300) -> bool:
        """
        Fetch 필요 여부 확인.

        Args:
            source: 데이터 소스
            min_interval_seconds: 최소 fetch 간격 (초)

        Returns:
            True if fetch needed
        """
        last_fetch = self.get_last_fetch(source)

        if last_fetch is None:
            return True

        elapsed = (datetime.now() - last_fetch).total_seconds()
        return elapsed >= min_interval_seconds

    # =========================================================================
    # Utility Methods
    # =========================================================================

    def clear_source(self, source: str) -> int:
        """
        특정 소스의 모든 캐시 삭제.

        Args:
            source: 데이터 소스

        Returns:
            삭제된 키 수
        """
        try:
            pattern = f"{self.KEY_PREFIX}*{source}*"
            deleted = 0

            cursor = 0
            while True:
                cursor, keys = self.client.scan(
                    cursor=cursor, match=pattern, count=100
                )
                if keys:
                    deleted += self.client.delete(*keys)

                if cursor == 0:
                    break

            logger.info(f"[Cache] Cleared {source}: {deleted} keys")
            return deleted

        except Exception as e:
            logger.error(f"[Cache] Clear source failed: {e}")
            return 0

    def clear_all(self) -> int:
        """
        모든 매크로 데이터 캐시 삭제.

        Returns:
            삭제된 키 수
        """
        try:
            pattern = f"{self.KEY_PREFIX}*"
            deleted = 0

            cursor = 0
            while True:
                cursor, keys = self.client.scan(
                    cursor=cursor, match=pattern, count=100
                )
                if keys:
                    deleted += self.client.delete(*keys)

                if cursor == 0:
                    break

            logger.info(f"[Cache] Cleared all: {deleted} keys")
            return deleted

        except Exception as e:
            logger.error(f"[Cache] Clear all failed: {e}")
            return 0

    def get_stats(self) -> Dict[str, Any]:
        """
        캐시 통계 조회.

        Returns:
            통계 정보 딕셔너리
        """
        try:
            stats = {
                "data_points": 0,
                "snapshots": 0,
                "news": 0,
                "sources": [],
            }

            # Count by type
            for pattern, key in [
                (f"{self.KEY_POINT}*", "data_points"),
                (f"{self.KEY_SNAPSHOT}*", "snapshots"),
                (f"{self.KEY_NEWS}*", "news"),
            ]:
                cursor = 0
                while True:
                    cursor, keys = self.client.scan(
                        cursor=cursor, match=pattern, count=100
                    )
                    stats[key] += len(keys)

                    if cursor == 0:
                        break

            # Get unique sources
            sources = set()
            cursor = 0
            while True:
                cursor, keys = self.client.scan(
                    cursor=cursor, match=f"{self.KEY_LAST_FETCH}*", count=100
                )
                for key in keys:
                    key_str = key.decode() if isinstance(key, bytes) else key
                    source = key_str.replace(self.KEY_LAST_FETCH, "")
                    sources.add(source)

                if cursor == 0:
                    break

            stats["sources"] = list(sources)

            return stats

        except Exception as e:
            logger.error(f"[Cache] Get stats failed: {e}")
            return {}


# 글로벌 인스턴스
_global_cache: Optional[MacroDataCache] = None


def get_macro_cache() -> MacroDataCache:
    """글로벌 캐시 인스턴스 반환"""
    global _global_cache
    if _global_cache is None:
        _global_cache = MacroDataCache()
    return _global_cache
